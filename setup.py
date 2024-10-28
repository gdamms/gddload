from setuptools import setup, find_packages

with open('requirements.txt') as f:
    required = f.read().splitlines()

setup(
    name='gddload',
    version='0.2.2',
    license="MIT",
    description='A simple package to download files from Google Drive',
    long_description=open('README.md').read(),
    author='gdamms',
    author_email='damguillotin@gmail.com',
    url='https://www.github.com/gdamms/gddload',
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=required,
    entry_points = {
        'console_scripts': ['gddload=gddload.gddload:main'],
    }
)
