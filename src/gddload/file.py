import os
import hashlib

from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

from .config import Config
from .size import Size
from .progress import Progress


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

    @staticmethod
    def requires_details(status: int) -> bool:
        """Return True if the status requires details.

        Args:
            status (int): The status of the file.

        Returns:
            bool: True if the status requires details.
        """
        return (
            status == FileStatus.CORRUPTED or
            status == FileStatus.FAILED or
            status == FileStatus.ALREADY_PRESENT or
            status == FileStatus.DOWNLOADING
        )


class FileType:
    """The type of a file."""

    UNKNOWN = -1
    FILE = 0
    FOLDER = 1


class File:
    """A file in Google Drive."""

    def __init__(self, id: str, dirname: str, config: Config) -> None:
        """Initialize the file.

        Args:
            id (str): The Google Drive file ID.
            dirname (str): The directory name to save the file.
            config (Config): The configuration of the program.
        """
        self.id = id
        self.dirname = dirname
        self.config = config
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

    @property
    def size(self):
        if self.type == FileType.FOLDER:
            self._size.size = sum([child.size for child in self.children])
        return self._size.size

    @size.setter
    def size(self, size: int):
        self._size.size = size

    @property
    def progress(self) -> Progress:
        if self.size == 0:
            self._progress.progress = 1

        if self.type == FileType.FOLDER:
            self._progress.progress = sum([child.progress * child.size for child in self.children]) / self.size

        return self._progress

    @progress.setter
    def progress(self, progress: float):
        self._progress.progress = progress
        self.update()

    @property
    def path(self) -> str:
        return os.path.join(self.dirname, self.name)

    def update(self):
        if self.parent is not None:
            self.parent.update()
        else:
            print('\x1b[0;0H\x1b[J', end='', flush=True)
            print(self.__str__(), flush=True)

    def child(self, id: str) -> 'File':
        child = File(id, self.path, self.config)
        self.children.append(child)
        child.parent = self
        return child

    def __str__(self):
        """Return file tree as a string."""
        if self.type == FileType.FILE:
            color = FileStatus.ansify(self.status)
            text = color + f"{self.name} - {self._size} {self.progress}" + ANSI.DEFAULT
            return text
        elif self.type == FileType.FOLDER:
            color = FileStatus.ansify(self.status)
            text = color + f"{self.name}/ - {self._size} {self.progress}" + ANSI.DEFAULT
            if FileStatus.requires_details(self.status):
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
            else:
                text += ' ...'
            return text
        elif self.type == FileType.UNKNOWN:
            return f"Unknown file {self.id}"

    def should_download(self) -> bool:
        """Check if the file should be downloaded.

        Returns:
            bool: True if the file should be downloaded, False otherwise.
        """
        assert self.type == FileType.FILE

        if self.config.force:
            return True

        if self.status == FileStatus.PENDING:
            return True

        if self.status == FileStatus.CORRUPTED or self.status == FileStatus.ALREADY_PRESENT:
            return self.config.overwrite

        if self.status == FileStatus.ALREADY_CHECKED:
            return False

        raise Exception(f'Unexpected status {self.status}')

    def download(self):
        """Download a file from Google Drive."""
        self.status = FileStatus.DOWNLOADING

        request = self.config.service.files().get_media(fileId=self.id)
        with open(self.path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()
                self.progress = status.progress()

        self.status = FileStatus.DOWNLOADED

    def download_file(self):
        """Download a file from Google Drive."""
        if self.should_download():
            self.status = FileStatus.DOWNLOADING
            if self.config.check:
                self.download_with_retry(self.config.retry)
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
        try:
            # get the file attributes
            response = self.config.service.files().get(
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
                    if not self.config.force and self.config.check:
                        self.precheck_file()
            elif self.type == FileType.FOLDER:
                page_token = None
                while True:
                    # get the children files
                    children_response = self.config.service.files().list(
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

                # update the size of the folder
                self.size = sum([child.size for child in self.children])

        except HttpError as error:
            print(f"An error occurred: {error}", flush=True)
