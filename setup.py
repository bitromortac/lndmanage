import re, setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

with open('./lndmanage/__init__.py', 'r') as f:
    MATCH_EXPR = "__version__[^'\"]+(['\"])([^'\"]+)"
    VERSION = re.search(MATCH_EXPR, f.read()).group(2)

# to package, run:
# pip install setuptools wheel sdist twine
# python3 setup.py sdist bdist_wheel
setuptools.setup(
    name="lndmanage",
    version=VERSION,
    author="bitromortac",
    author_email="bitromortac@protonmail.com",
    description="Channel management tool for lightning network daemon (LND) "
                "operators.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/bitromortac/lndmanage",
    packages=setuptools.find_packages(),
    install_requires=[
        'wheel',
        'cycler==0.10.0',
        'decorator==4.4.0',
        'googleapis-common-protos==1.5.9',
        'grpcio==1.19.0',
        'grpcio-tools==1.13.0',
        'kiwisolver==1.0.1',
        'networkx==2.4',
        'numpy==1.16.2',
        'protobuf==3.7.1',
        'Pygments==2.4.2',
        'pyparsing==2.4.0',
        'python-dateutil==2.8.0',
        'six==1.12.0',
    ],
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    entry_points={
        "console_scripts": [
            "lndmanage = lndmanage.lndmanage:main",
        ]
    },
)
