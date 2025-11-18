#!/usr/bin/env python3
"""
Setup configuration for cnpg-mcp-server.

This allows the server to be installed as a Python package.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

# Read requirements
requirements = []
with open("requirements.txt") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="cnpg-mcp-server",
    version="1.2.0",
    author="helxplatform",
    author_email="",
    description="MCP server for managing PostgreSQL clusters using CloudNativePG in Kubernetes",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/helxplatform/cnpg-mcp",
    project_urls={
        "Bug Tracker": "https://github.com/helxplatform/cnpg-mcp/issues",
        "Documentation": "https://github.com/helxplatform/cnpg-mcp#readme",
        "Source Code": "https://github.com/helxplatform/cnpg-mcp",
    },
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Database",
        "Topic :: System :: Systems Administration",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords="postgresql postgres cloudnativepg cnpg kubernetes k8s database mcp cluster-management ha",
    packages=["src"],
    package_dir={"src": "src"},
    py_modules=["src.cnpg_mcp_server", "src.auth_oidc"],
    python_requires=">=3.11",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "cnpg-mcp-server=src.cnpg_mcp_server:run",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["README.md", "LICENSE", "requirements.txt", "example-cluster.yaml", "rbac.yaml"],
    },
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
            "mypy>=1.0.0",
        ],
    },
)
