import argparse


class Config:
    """The configuration of the program."""

    def __init__(
            self,
            file_id: str,
            save_path: str,
            check: bool,
            overwrite: bool,
            force: bool,
            retry: int,
    ) -> None:
        """Initialize the configuration.

        Args:
            file_id (str): The Google Drive file ID
            save_path (str): The path to save the files
            check (bool): Check the sha256 of the files before and after download
            overwrite (bool): Overwrite the file if it already exists. If used with --check, only files that are corrupted will be overwritten
            force (bool): Force the download of the file even if it already exists
            retry (int): The number of retries in case of error. (implies --check)
        """
        self.file_id = file_id
        self.save_path = save_path
        self.check = check or retry > 0
        self.overwrite = overwrite
        self.force = force
        self.retry = retry

    @staticmethod
    def parse_args() -> 'Config':
        """Parse the command line arguments."""
        parser = argparse.ArgumentParser(description='Download files from Google Drive')
        parser.add_argument('file_id', type=str, help='The Google Drive file ID')
        parser.add_argument('--save_path', type=str, default='.', help='The path to save the files')
        parser.add_argument('--check', action='store_true',
                            help='Check the sha256 of the files before and after download')
        parser.add_argument('--overwrite', action='store_true',
                            help='Overwrite the file if it already exists. If used with --check, only files that are corrupted will be overwritten')
        parser.add_argument('--force', action='store_true',
                            help='Force the download of the file even if it already exists')
        parser.add_argument('--retry', type=int, default=0,
                            help='The number of retries in case of error. (implies --check)')
        args = parser.parse_args()

        config = Config(
            file_id=args.file_id,
            save_path=args.save_path,
            check=args.check,
            overwrite=args.overwrite,
            force=args.force,
            retry=args.retry,
        )
        return config
