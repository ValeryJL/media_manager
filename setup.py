from setuptools import setup, find_packages

setup(
    name="media_manager",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click",
        "pyyaml",
        "aria2p[tui]",
        "guessit",
        "cinemagoer",
        "rich",
        "questionary"
    ],
    entry_points={
        "console_scripts": [
            "media-manager=media_manager.cli:cli",
        ],
    },
)
