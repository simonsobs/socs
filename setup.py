from distutils.core import setup

import versioneer

setup(name = 'socs',
      version = versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      description = 'Simons Observatory Control System',
      package_dir = {'socs': 'socs'},
      packages = ['socs',])
