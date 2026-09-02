from setuptools import setup, find_packages

setup(
    name="claude-docs-rag",
    version="1.0.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        # <2 is load-bearing — mcp 2.x drops the v1 low-level Server API (D-0001).
        # Keep in sync with requirements.txt.
        "mcp>=1.28,<2",
        "chromadb>=0.4.22",
        "sentence-transformers>=2.2.2",
        "rank-bm25>=0.2.2",
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.0",
        "markdownify>=0.11.6",
        "numpy>=1.24.0",
        "tiktoken>=0.5.0",
        "PyYAML>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "claude-docs-rag=docs_rag.server:main",
        ],
    },
    python_requires=">=3.9",
)