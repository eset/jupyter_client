"""Tools for managing kernel specs"""

# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.

import io
import json
import os
import shutil
import warnings

pjoin = os.path.join

from ipython_genutils.py3compat import PY3
from traitlets import HasTraits, List, Unicode, Dict, Set
from traitlets.config import LoggingConfigurable

from jupyter_core.paths import jupyter_data_dir, jupyter_path, SYSTEM_JUPYTER_PATH


NATIVE_KERNEL_NAME = 'python3' if PY3 else 'python2'

try:
    from ipykernel.kernelspec import RESOURCES as NATIVE_RESOURCE_DIR
except ImportError:
    NATIVE_RESOURCE_DIR = None


class KernelSpec(HasTraits):
    argv = List()
    display_name = Unicode()
    language = Unicode()
    env = Dict()
    resource_dir = Unicode()

    @classmethod
    def from_resource_dir(cls, resource_dir):
        """Create a KernelSpec object by reading kernel.json

        Pass the path to the *directory* containing kernel.json.
        """
        kernel_file = pjoin(resource_dir, 'kernel.json')
        with io.open(kernel_file, 'r', encoding='utf-8') as f:
            kernel_dict = json.load(f)
        return cls(resource_dir=resource_dir, **kernel_dict)

    def to_dict(self):
        d = dict(argv=self.argv,
                 env=self.env,
                 display_name=self.display_name,
                 language=self.language,
                )

        return d

    def to_json(self):
        """Serialise this kernelspec to a JSON object.

        Returns a string.
        """
        return json.dumps(self.to_dict())

def _is_kernel_dir(path):
    """Is ``path`` a kernel directory?"""
    return os.path.isdir(path) and os.path.isfile(pjoin(path, 'kernel.json'))

def _list_kernels_in(dir):
    """Return a mapping of kernel names to resource directories from dir.

    If dir is None or does not exist, returns an empty dict.
    """
    if dir is None or not os.path.isdir(dir):
        return {}
    return {f.lower(): pjoin(dir, f) for f in os.listdir(dir)
                        if _is_kernel_dir(pjoin(dir, f))}

class NoSuchKernel(KeyError):
    def __init__(self, name):
        self.name = name

class KernelSpecManager(LoggingConfigurable):
    data_dir = Unicode()
    def _data_dir_default(self):
        return jupyter_data_dir()

    user_kernel_dir = Unicode()
    def _user_kernel_dir_default(self):
        return pjoin(self.data_dir, 'kernels')

    whitelist = Set(config=True,
        help="""Whitelist of allowed kernel names.

        By default, all installed kernels are allowed.
        """
    )
    kernel_dirs = List(
        help="List of kernel directories to search. Later ones take priority over earlier."
    )
    def _kernel_dirs_default(self):
        dirs = jupyter_path('kernels')
        # At some point, we should stop adding .ipython/kernels to the path,
        # but the cost to keeping it is very small.
        try:
            from IPython.paths import get_ipython_dir
        except ImportError:
            try:
                from IPython.utils.path import get_ipython_dir
            except ImportError:
                # no IPython, no ipython dir
                get_ipython_dir = None
        if get_ipython_dir is not None:
            dirs.append(os.path.join(get_ipython_dir(), 'kernels'))
        return dirs

    def find_kernel_specs(self):
        """Returns a dict mapping kernel names to resource directories."""
        d = {}
        for kernel_dir in self.kernel_dirs:
            kernels = _list_kernels_in(kernel_dir)
            for kname, spec in kernels.items():
                if kname not in d:
                    self.log.debug("Found kernel %s in %s", kname, kernel_dir)
                    d[kname] = spec

        if NATIVE_KERNEL_NAME not in d:
            if NATIVE_RESOURCE_DIR is None:
                self.log.warn("Native kernel (%s) is not available", NATIVE_KERNEL_NAME)
            else:
                self.log.debug("Native kernel (%s) available from %s",
                               NATIVE_KERNEL_NAME, NATIVE_RESOURCE_DIR)
                d[NATIVE_KERNEL_NAME] = NATIVE_RESOURCE_DIR

        if self.whitelist:
            # filter if there's a whitelist
            d = {name:spec for name,spec in d.items() if name in self.whitelist}
        return d
        # TODO: Caching?

    def get_kernel_spec(self, kernel_name):
        """Returns a :class:`KernelSpec` instance for the given kernel_name.

        Raises :exc:`NoSuchKernel` if the given kernel name is not found.
        """
        d = self.find_kernel_specs()
        try:
            resource_dir = d[kernel_name.lower()]
        except KeyError:
            raise NoSuchKernel(kernel_name)

        if d == NATIVE_RESOURCE_DIR:
            try:
                from ipykernel.kernelspec import get_kernel_dict
            except ImportError:
                # It should be impossible to reach this, but let's play it safe
                raise NoSuchKernel(kernel_name)
            else:
                return KernelSpec(resource_dir=resource_dir, **get_kernel_dict())

        return KernelSpec.from_resource_dir(resource_dir)

    def _get_destination_dir(self, kernel_name, user=False):
        if user:
            return os.path.join(self.user_kernel_dir, kernel_name)
        else:
            return os.path.join(SYSTEM_JUPYTER_PATH[0], 'kernels', kernel_name)


    def install_kernel_spec(self, source_dir, kernel_name=None, user=False,
                            replace=None):
        """Install a kernel spec by copying its directory.

        If ``kernel_name`` is not given, the basename of ``source_dir`` will
        be used.

        If ``user`` is False, it will attempt to install into the systemwide
        kernel registry. If the process does not have appropriate permissions,
        an :exc:`OSError` will be raised.
        """
        if not kernel_name:
            kernel_name = os.path.basename(source_dir)
        kernel_name = kernel_name.lower()
        
        if replace is not None:
            warnings.warn(
                "replace is ignored. Installing a kernelspec always replaces an existing installation",
                DeprecationWarning,
                stacklevel=2,
            )
        
        destination = self._get_destination_dir(kernel_name, user=user)
        self.log.debug('Installing kernelspec in %s', destination)

        if os.path.isdir(destination):
            self.log.info('Removing existing kernelspec in %s', destination)
            shutil.rmtree(destination)

        shutil.copytree(source_dir, destination)
        self.log.info('Installed kernelspec %s in %s', kernel_name, destination)
        return destination

    def install_native_kernel_spec(self, user=False):
        """DEPRECATED: Use ipykernel.kenelspec.install"""
        warnings.warn("install_native_kernel_spec is deprecated."
            " Use ipykernel.kernelspec import install.", stacklevel=2)
        from ipykernel.kernelspec import install
        install(self, user=user)


def find_kernel_specs():
    """Returns a dict mapping kernel names to resource directories."""
    return KernelSpecManager().find_kernel_specs()

def get_kernel_spec(kernel_name):
    """Returns a :class:`KernelSpec` instance for the given kernel_name.

    Raises KeyError if the given kernel name is not found.
    """
    return KernelSpecManager().get_kernel_spec(kernel_name)

def install_kernel_spec(source_dir, kernel_name=None, user=False, replace=False):
    return KernelSpecManager().install_kernel_spec(source_dir, kernel_name,
                                                    user, replace)

install_kernel_spec.__doc__ = KernelSpecManager.install_kernel_spec.__doc__

def install_native_kernel_spec(user=False):
    return KernelSpecManager().install_native_kernel_spec(user=user)

install_native_kernel_spec.__doc__ = KernelSpecManager.install_native_kernel_spec.__doc__
