"""Setup script for the CLA system."""

import re
import codecs
from os import path
from setuptools import setup, find_packages

def find_version(filename):
    """Helper function to find the currently CLA system version."""
    with open(filename) as fhandle:
        version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]",
                                  fhandle.read(), re.M)
        if version_match:
            return version_match.group(1)
        raise RuntimeError("Unable to find version string.")

setup(
    name='cla',
    version=find_version('cla/__init__.py'),
    description='REST endpoint to manage CLAs',
    long_description='See the CLA GitHub repository for more details: ' + \
                     'https://github.com/linuxfoundation/cla',
    url='https://github.com/linuxfoundation/cla',
    author='***REMOVED*** ***REMOVED***',
    author_email='***REMOVED***@linuxfoundation.org',
    #license='BSD',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Framework :: Hug',
        'Intended Audience :: Developers',
        #'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.6',
    ],
    keywords='cla',
    packages=find_packages(),
    install_requires=['boto>=2.48.0,<3.0',
                      'boto3>=1.4.4,<2.0',
                      'gossip>=2.2.0,<3.0',
                      'gunicorn>=19.7.1,<20.0',
                      'hug>=2.2.0,<3.0',
                      'pydocusign>=1.2.0,<2.0',
                      'pygithub>=1.34.0,<2.0',
                      'pynamodb>=2.1.6,<3.0',
                      'python-gitlab>=0.21.2,<1.0',
                      'requests-oauthlib>=0.8.0,<1.0',
                      'python-jose>=1.4.0'],
                      #'git+https://github.com/ibotty/keycloak-python.git'],
    extras_require={'dev': ['pylint'], 'test': ['nose', 'coverage']},
    entry_points={'console_scripts': []},
)
