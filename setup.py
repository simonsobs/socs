from setuptools import setup, find_packages

import versioneer

with open("README.rst", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(name = 'socs',
      long_description=long_description,
      long_description_content_type="text/x-rst",
      version = versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      description = 'Simons Observatory Control System',
      package_dir = {'socs': 'socs'},
      packages = find_packages(),
      url="https://github.com/simonsobs/socs",
      project_urls={
          "Source Code": "https://github.com/simonsobs/ocs",
          "Documentation": "https://ocs.readthedocs.io/",
          "Bug Tracker": "https://github.com/simonsobs/ocs/issues",
      },
      classifiers=[
          "Programming Language :: Python :: 3",
          "License :: OSI Approved :: BSD License",
          "Intended Audience :: Science/Research",
          "Topic :: Scientific/Engineering :: Astronomy",
          "Framework :: Twisted",
      ],
      python_requires=">=3.6",
      install_requires=[
          'ocs',
          'autobahn[serialization]',
          'twisted',
          'pyserial',
          'sqlalchemy',
          'pysnmp',
      ],
)
