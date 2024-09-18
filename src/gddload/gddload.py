from .config import Config
from .file import File


def main():
    config = Config.parse_args()

    # TODO: no file found or no permission or ...

    print("\x1b[H\x1b[2J", end='', flush=True)  # clear the screen (but not the scrollback buffer, ie. ctrl+l)
    root_file = File(config.file_id, dirname=config.save_path, config=config)
    root_file.scan()
    root_file.download_recursive()


if __name__ == "__main__":
    main()
