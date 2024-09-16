from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import hashlib
import argparse
import sys


class ANSI:
    DEFAULT = '\x1b[0m'
    GREY = '\x1b[90m'
    RED = '\x1b[91m'
    GREEN = '\x1b[92m'
    YELLOW = '\x1b[93m'
    BLUE = '\x1b[94m'
    MAGENTA = '\x1b[95m'
    CYAN = '\x1b[96m'
    WHITE = '\x1b[97m'


class FileStatus:
    PENDING = 0
    DOWNLOADING = 1
    DOWNLOADED = 2
    ALREADY_PRESENT = 3
    CORRUPTED = 4
    FAILED = 6
    CHECKED = 7
    ALREADY_CHECKED = 8

    @staticmethod
    def ansify(status: int) -> str:
        if status == FileStatus.PENDING:
            return ANSI.CYAN
        elif status == FileStatus.DOWNLOADING:
            return ANSI.BLUE
        elif status == FileStatus.DOWNLOADED:
            return ANSI.GREEN
        elif status == FileStatus.ALREADY_PRESENT:
            return ANSI.YELLOW
        elif status == FileStatus.CORRUPTED:
            return ANSI.RED
        elif status == FileStatus.FAILED:
            return ANSI.RED
        elif status == FileStatus.CHECKED:
            return ANSI.GREEN
        elif status == FileStatus.ALREADY_CHECKED:
            return ANSI.GREEN
        else:
            return ANSI.DEFAULT


class FileType:
    UNKNOWN = -1
    FILE = 0
    FOLDER = 1


class File:
    def __init__(self, id: str, dirname: str):
        self.id = id
        self.dirname = dirname
        self.name = ''
        self._size = 0
        self.type = FileType.UNKNOWN
        self.sha256 = ''
        self.done_size = 0
        self.status = FileStatus.PENDING
        self.children = []

    def set_size(self, size: int):
        self._size = size

    @property
    def size(self):
        if self.type == FileType.FOLDER:
            self._size = sum([child.size for child in self.children])
        return self._size

    def print(self, indent=''):
        """Print the file info.

        Args:
            indent (str, optional): The parent indetation. Defaults to ''.
        """
        color = FileStatus.ansify(self.status)
        text = indent + color + f"{self.name} - {self.formatted_size} {self.formatted_progress}" + ANSI.DEFAULT
        print(text, flush=True)
        if indent == '':
            child_indent = ''
        else:
            child_indent = indent[:-2] + ('  ' if indent[-2:] == '└ ' else '│ ')
        for child_i, child in enumerate(self.children):
            child_indent_i = '└ ' if child_i == len(self.children) - 1 else '├ '
            child.print(child_indent + child_indent_i)

    def should_download(self) -> bool:
        """Check if the file should be downloaded.

        Returns:
            bool: True if the file should be downloaded, False otherwise.
        """
        assert self.type == FileType.FILE

        if config['force']:
            return True

        if self.status == FileStatus.PENDING:
            return True

        if self.status == FileStatus.CORRUPTED or self.status == FileStatus.ALREADY_PRESENT:
            return config['overwrite']

        if self.status == FileStatus.ALREADY_CHECKED:
            return False

        raise Exception(f'Unexpected status {self.status}')

    def download(self):
        """Download a file from Google Drive."""
        self.status = FileStatus.DOWNLOADING

        request = service.files().get_media(fileId=self.id)
        with open(self.path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()
                self.done_size = status.resumable_progress
                print_root_file()

        self.status = FileStatus.DOWNLOADED

    def download_file(self):
        """Download a file from Google Drive."""
        global service

        if self.should_download():
            self.status = FileStatus.DOWNLOADING
            if config['check'] or config['retry'] > 0:
                self.download_with_retry(config['retry'])
            else:
                self.download()

    def download_with_check(self) -> bool:
        """Download a file from Google Drive. Check the integrity of the file.

        Returns:
            bool: True if the file is correct, False otherwise.
        """
        self.download()
        return self.postcheck_file()

    def download_with_retry(self, retry: int) -> bool:
        """Download a file from Google Drive. Retry in case of error.

        Args:
            retry (int): The number of retries.

        Returns:
            bool: True if the file is correct, False otherwise.
        """
        if retry == 0:
            return self.download_with_check()

        if self.download_with_check():
            return True
        else:
            return self.download_with_retry(retry - 1)

    def download_folder(self):
        """Download a folder from Google Drive."""
        assert self.type == FileType.FOLDER

        self.status = FileStatus.DOWNLOADING

        if not os.path.exists(self.path):
            os.makedirs(self.path)

        for child in self.children:
            child.download_recursive()

        self.status = FileStatus.DOWNLOADED

    def download_recursive(self):
        """Recursively download a file from Google Drive."""
        if self.type == FileType.FOLDER:
            self.download_folder()
        elif self.type == FileType.FILE:
            self.download_file()

    def check_file(self) -> bool:
        """Check the integrity of a file from Google Drive.

        Returns:
            bool: True if the file is correct, False otherwise.
        """
        assert os.path.exists(self.path)

        with open(self.path, 'rb') as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()

        return sha256 == self.sha256

    def precheck_file(self) -> bool:
        """Precheck the integrity of a file from Google Drive.

        Returns:
            bool: True if the file is correct, False otherwise.
        """
        checked = self.check_file()
        if checked:
            self.status = FileStatus.ALREADY_CHECKED
            self.done_size = self.size
        else:
            self.status = FileStatus.CORRUPTED

        print_root_file()

        return checked

    def postcheck_file(self) -> bool:
        """Postcheck the integrity of a file from Google Drive.

        Returns:
            bool: True if the file is correct, False otherwise.
        """
        checked = self.check_file()
        if checked:
            self.status = FileStatus.CHECKED
            self.done_size = self.size
        else:
            self.status = FileStatus.FAILED

        print_root_file()

        return checked

    def scan(self):
        """Scan a file from Google Drive."""
        global service

        try:
            # get the file attributes
            response = service.files().get(
                fileId=self.id,
                fields='id,name,mimeType,size,sha256Checksum',
            ).execute()

            # update the file attributes
            self.id = response['id']
            self.name = response['name']
            if 'folder' in response['mimeType']:
                self.type = FileType.FOLDER
                self.set_size(0)
            else:
                self.type = FileType.FILE
                self.set_size(int(response['size']))
            self.children = []
            self.done_size = 0
            self.sha256 = response.get('sha256Checksum', '')
            self.status = FileStatus.PENDING

            if self.type == FileType.FILE:
                if os.path.exists(self.path):
                    self.status = FileStatus.ALREADY_PRESENT
                    if not config['force'] and (config['check'] or config['retry'] > 0):
                        self.precheck_file()
            elif self.type == FileType.FOLDER:
                page_token = None
                while True:
                    # get the children files
                    children_response = service.files().list(
                        q=f"'{self.id}' in parents",
                        spaces="drive",
                        fields="nextPageToken, files(id)",
                        pageToken=page_token,
                    ).execute()
                    children_files = children_response.get("files", [])

                    # scan the children files
                    for f in children_files:
                        child_file = File(f['id'], self.path)
                        self.children.append(child_file)  # add the child first so that the parent is updated
                        child_file.scan()

                    # break if there are no more children batch
                    page_token = children_response.get("nextPageToken", None)
                    if page_token is None:
                        break

        except HttpError as error:
            print(f"An error occurred: {error}", flush=True)

        print_root_file()

    @property
    def path(self):
        return os.path.join(self.dirname, self.name)

    @property
    def formatted_size(self):
        return format_size(self.size)

    @property
    def formatted_progress(self):
        return format_progress(self.progress)

    @property
    def progress(self):
        if self.type == FileType.FOLDER:
            self.done_size = sum([child.done_size for child in self.children])
        return self.done_size / self.size if self.size > 0 else 1.0


def parse_args():
    """Parse the command line arguments."""

    parser = argparse.ArgumentParser(description='Download files from Google Drive')
    parser.add_argument('file_id', type=str, help='The Google Drive file ID')
    parser.add_argument('--save_path', type=str, default='.', help='The path to save the files')
    parser.add_argument('--check', action='store_true', help='Check the sha256 of the files before and after download')
    parser.add_argument('--overwrite', action='store_true',
                        help='Overwrite the file if it already exists. If used with --check, only files that are corrupted will be overwritten')
    parser.add_argument('--force', action='store_true', help='Force the download of the file even if it already exists')
    parser.add_argument('--retry', type=int, default=0,
                        help='The number of retries in case of error. (implies --check)')
    args = parser.parse_args()

    global config
    config = {}
    config['file_id'] = args.file_id
    config['save_path'] = args.save_path
    config['check'] = args.check
    config['overwrite'] = args.overwrite
    config['force'] = args.force
    config['retry'] = args.retry


creds = service_account.Credentials.from_service_account_file(
    'key.json',
    scopes=['https://www.googleapis.com/auth/drive']
)
service = build("drive", "v3", credentials=creds)
root_file = None
BAR_LENGTH = 4

status = 'idle'


def main():
    global root_file, status, config

    parse_args()

    status = 'scanning'

    root_file = File(config['file_id'], dirname=config['save_path'])
    root_file.scan()

    # TODO: no file found or no permission or ...

    status = 'downloading'
    root_file.download_recursive()

    status = 'done'
    print_root_file()


def print_root_file():
    global root_file, status
    if not root_file:
        raise Exception('Root file is not set')  # TODO: better error handling
    print('\x1b[0;0H\x1b[J', end='', flush=True)
    print(f"Status: {status}", flush=True)
    root_file.print()


def format_size(size: float) -> str:
    """Format the size in bytes to a human readable format.

    Args:
        size (float): The size in bytes.

    Returns:
        str: The size in a human readable format.
    """
    units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB']
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    return f"{size:.2f} {units[unit]}"


def format_progress(progress: float) -> str:
    """Format the progress bar.

    Args:
        progress (float): The progress between 0 and 1.

    Returns:
        str: The progress bar.
    """
    if progress < 0 or progress > 1:
        print(f"warning: progress {progress} is not between 0 and 1", flush=True, file=sys.stderr)
        progress = max(0, min(progress, 1))
    bar = '━' * int(BAR_LENGTH * progress) + ('╾' if progress * BAR_LENGTH % 1 >= 0.5 else '─') + '─' * BAR_LENGTH
    bar = bar[:BAR_LENGTH]
    return f"{bar} {100*progress:.2f}%"


if __name__ == "__main__":
    # file_id = '1GwXP-KpWOxOenOxITTsURJZQ_1pkd4-j' # MEAD
    # file_id = '15UjOIbGJ2NapRG5SD288Zb6nlnY9iTaj'  # test
    main()
