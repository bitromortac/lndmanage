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
        'cycler==0.10.0',
        'decorator==4.4.2',
        'googleapis-common-protos==1.52.0',
        'grpcio==1.31.0',
        'grpcio-tools==1.31.0',
        'kiwisolver==1.2.0',
        'networkx==2.4',
        'numpy==1.19.1',
        'protobuf==3.12.4',
        'Pygments==2.6.1',
        'pyparsing==2.4.7',
        'python-dateutil==2.8.1',
        'six==1.15.0',
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
