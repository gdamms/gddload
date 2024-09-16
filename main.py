from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import hashlib
import argparse
import sys


class Size:
    """A size in bytes."""

    UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']

    def __init__(self, size: int) -> None:
        """Initialize the size.

        Args:
            size (int): The size in bytes.
        """
        self.size = size

    def __str__(self) -> str:
        """Return the size as a string.

        Returns:
            str: The size as a string.
        """
        unit = 0
        while self.size >= 1024 and unit < len(Size.UNITS) - 1:
            self.size /= 1024
            unit += 1
        return f"{self.size:.2f} {Size.UNITS[unit]}"


class Progress:
    """A progress bar."""

    def __init__(self, progress: float) -> None:
        """Initialize the progress bar.

        Args:
            progress (float): The progress between 0 and 1.
        """
        self.progress = progress

    @property
    def progress(self) -> float:
        return self._progress

    @progress.setter
    def progress(self, progress: float):
        if not 0 <= progress <= 1:
            print(f"warning: progress {progress} is not between 0 and 1", flush=True, file=sys.stderr)
            progress = max(0, min(progress, 1))
        self._progress = progress

    def __str__(self) -> str:
        """Return the progress bar as a string.

        Returns:
            str: The progress bar as a string.
        """
        bar = '━' * int(BAR_LENGTH * self.progress) + ('╾' if self.progress *
                                                       BAR_LENGTH % 1 >= 0.5 else '─') + '─' * BAR_LENGTH
        bar = bar[:BAR_LENGTH]
        return f"{bar} {100*self.progress:.2f}%"


class ANSI:
    """ANSI escape codes."""
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
    """The status of a file."""
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
        """Return the ANSI escape code for the status.

        Args:
            status (int): The status of the file.

        Returns:
            str: The ANSI escape code.
        """
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
    """The type of a file."""
    UNKNOWN = -1
    FILE = 0
    FOLDER = 1


class File:
    """A file in Google Drive."""

    def __init__(self, id: str, dirname: str) -> None:
        """Initialize the file.

        Args:
            id (str): The Google Drive file ID.
            dirname (str): The directory name to save the file.
        """
        self.id = id
        self.dirname = dirname
        self.name = ''
        self._size = Size(0)
        self.type = FileType.UNKNOWN
        self.sha256 = ''
        self._progress = Progress(0)
        self._status = FileStatus.PENDING
        self.children = []
        self.parent = None

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, status: int):
        self._status = status
        self.update()

    def update(self):
        if self.parent is not None:
            self.parent.update()
        else:
            print('\x1b[0;0H\x1b[J', end='', flush=True)
            print(self.__str__(), flush=True)

    def child(self, id: str) -> 'File':
        child = File(id, self.path)
        self.children.append(child)
        child.parent = self
        return child

    @property
    def size(self):
        if self.type == FileType.FOLDER:
            self._size.size = sum([child.size for child in self.children])
        return self._size.size

    @size.setter
    def size(self, size: int):
        self._size.size = size

    def __str__(self):
        """Return file tree as a string."""
        if self.type == FileType.FILE:
            color = FileStatus.ansify(self.status)
            text = color + f"{self.name} - {self._size} {self._progress}" + ANSI.DEFAULT
            return text
        elif self.type == FileType.FOLDER:
            color = FileStatus.ansify(self.status)
            text = color + f"{self.name}/ - {self._size} {self._progress}" + ANSI.DEFAULT
            for child_i, child in enumerate(self.children):
                # add the child text
                child_text = child.__str__()
                child_lines = child_text.split('\n')
                for line_i, line in enumerate(child_lines):
                    # add the child text with the correct indentation
                    if child_i == len(self.children) - 1:
                        if line_i == 0:
                            indent = '\n└ '
                        else:
                            indent = '\n  '
                    else:
                        if line_i == 0:
                            indent = '\n├ '
                        else:
                            indent = '\n│ '
                    text += indent + line
            return text
        elif self.type == FileType.UNKNOWN:
            return f"Unknown file {self.id}"

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
                self.progress = status.progress()

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
            self.progress = 1
        else:
            self.status = FileStatus.CORRUPTED

        return checked

    def postcheck_file(self) -> bool:
        """Postcheck the integrity of a file from Google Drive.

        Returns:
            bool: True if the file is correct, False otherwise.
        """
        checked = self.check_file()
        if checked:
            self.status = FileStatus.CHECKED
            self.progress = 1
        else:
            self.status = FileStatus.FAILED

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
                self.size = 0
            else:
                self.type = FileType.FILE
                self.size = int(response['size'])
            self.children = []
            self.sha256 = response.get('sha256Checksum', '')
            self.status = FileStatus.PENDING
            self.progress = 0

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
                        child_file = self.child(f['id'])
                        child_file.scan()

                    # break if there are no more children batch
                    page_token = children_response.get("nextPageToken", None)
                    if page_token is None:
                        break

        except HttpError as error:
            print(f"An error occurred: {error}", flush=True)

    @property
    def path(self) -> str:
        return os.path.join(self.dirname, self.name)

    @property
    def progress(self) -> float:
        if self.size == 0:
            return 1

        if self.type == FileType.FOLDER:
            self._progress.progress = sum([child.progress * child.size for child in self.children]) / self.size

        return self._progress.progress

    @progress.setter
    def progress(self, progress: float):
        self._progress.progress = progress
        self.update()


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


def main():
    global root_file, status, config

    parse_args()

    root_file = File(config['file_id'], dirname=config['save_path'])
    root_file.scan()

    # TODO: no file found or no permission or ...

    root_file.download_recursive()


if __name__ == "__main__":
    # file_id = '1GwXP-KpWOxOenOxITTsURJZQ_1pkd4-j' # MEAD
    # file_id = '15UjOIbGJ2NapRG5SD288Zb6nlnY9iTaj'  # test
    main()
