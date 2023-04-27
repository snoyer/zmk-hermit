from setuptools import setup

setup(
    name='zmk-hermit',
    version='0.0.2',
    py_modules=['zmk_hermit'],
    packages=[
        'zmk_hermit',
        'zmk_build',
    ],
    package_data={
        '': ['Dockerfile*']
    },
    include_package_data=True,
    entry_points='''
        [console_scripts]
        zmk-hermit=zmk_hermit.__main__:main
    ''',
    install_requires=[
        'docker',
    ],
)
