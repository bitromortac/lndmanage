import re, setuptools, os.path

description = "Channel management tool for lightning network daemon (LND) "
"operators.",
if os.path.exists("README.md"):
    with open("README.md", "r") as fh:
        long_description = fh.read()
else:
    long_description = description

with open("./lndmanage/__init__.py", "r") as f:
    MATCH_EXPR = "__version__[^'\"]+(['\"])([^'\"]+)"
    VERSION = re.search(MATCH_EXPR, f.read()).group(2)

# package:
# (venv) pip install build setuptools wheel sdist twine
# (venv) python3 -m build
# upload:
# (venv) twine upload --repository testpypi dist/*

setuptools.setup(
    name="lndmanage",
    version=VERSION,
    author="bitromortac",
    author_email="bitromortac@protonmail.com",
    description=description,
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/bitromortac/lndmanage",
    packages=setuptools.find_packages(),
    python_requires='>=3.9.0',
    install_requires=[
        "googleapis-common-protos==1.59.0",
        "grpcio==1.54.0",
        "grpcio-tools==1.54.0",
        "networkx==3.0",
        "numpy==1.24.3",
        "protobuf==3.20.3",
        "Pygments==2.15.1",
    ],
    extras_require={
        "test": [
            "lnregtest>=0.2.2",
        ]
    },
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
