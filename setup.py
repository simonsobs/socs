from setuptools import setup, find_packages

import versioneer

setup(name = 'socs',
      version = versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      description = 'Simons Observatory Control System',
      package_dir = {'socs': 'socs'},
      packages = find_packages())
