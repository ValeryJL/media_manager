from setuptools import setup, find_packages

setup(
    name="media_manager",
    version="0.2.0",
    packages=find_packages(),
    install_requires=[
        "click",
        "pyyaml",
        "guessit",
        "cinemagoer",
        "rich",
        "questionary",
        "pirate-get",
        "flet[desktop]",
        "pillow",
    ],
    entry_points={
        "console_scripts": [
            "media-manager=media_manager.cli:cli",
            "media-manager-gui=media_manager.gui:main",
        ],
    },
)
