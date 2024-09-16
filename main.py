from src.config import Config
from src.file import File


def main():
    global config

    config = Config.parse_args()

    print("\x1b[H\x1b[2J", end='', flush=True)  # clear the screen (but not the scrollback buffer, ie. ctrl+l)
    root_file = File(config.file_id, dirname=config.save_path, config=config)
    root_file.scan()

    # TODO: no file found or no permission or ...

    root_file.download_recursive()


if __name__ == "__main__":
    # file_id = '1GwXP-KpWOxOenOxITTsURJZQ_1pkd4-j' # MEAD
    # file_id = '15UjOIbGJ2NapRG5SD288Zb6nlnY9iTaj'  # test
    main()
