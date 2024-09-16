from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import hashlib
import argparse


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
    def __init__(self, id: str):
        self.id = id
        self.name = ''
        self.size = 0
        self.type = FileType.UNKNOWN
        self.sha256 = ''
        self.done_size = 0
        self.status = FileStatus.PENDING
        self.children = []

    def print(self, indent=''):
        """Print the file info.

        Args:
            indent (str, optional): The parent indetation. Defaults to ''.
        """
        # TODO: colors
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
    parser.add_argument('--check', action='store_true', help='Check the sha256 of the files')
    parser.add_argument('--overwrite', action='store_true',
                        help='Overwrite the file if it already exists but does not match the sha256')
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


def update_root_progress():
    global root_file
    if not root_file:
        # TODO: better error handling
        raise Exception('Root file is not set')


def download_folder(file: File, save_path: str):
    """Download a folder from Google Drive.

    Args:
        file (File): The file to download.
        save_path (str): The path to save the folder.
    """
    folder_path = os.path.join(save_path, file.name)

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    for child in file.children:
        download_file_recursive(child, folder_path)
    file.status = FileStatus.DOWNLOADED


def check_file(file: File, file_path: str) -> bool:
    """Check the integrity of a file from Google Drive.

    Args:
        file (File): The file to check.
        file_path (str): The path to the file.

    Returns:
        bool: True if the file is correct, False otherwise.
    """
    if not os.path.exists(file_path):
        raise Exception(f'File {file_path} does not exist')

    with open(file_path, 'rb') as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    return sha256 == file.sha256


def precheck_file(file: File, file_path: str) -> bool:
    """Precheck the integrity of a file from Google Drive.

    Args:
        file (File): The file to check.
        file_path (str): The path to the file.

    Returns:
        bool: True if the file is correct, False otherwise.
    """
    checked = check_file(file, file_path)
    if checked:
        file.status = FileStatus.ALREADY_CHECKED
        file.done_size = file.size
    else:
        file.status = FileStatus.CORRUPTED
    update_root_progress()
    print_root_file()
    return checked


def postcheck_file(file: File, file_path: str) -> bool:
    """Postcheck the integrity of a file from Google Drive.

    Args:
        file (File): The file to check.
        file_path (str): The path to the file.

    Returns:
        bool: True if the file is correct, False otherwise.
    """
    checked = check_file(file, file_path)
    if checked:
        file.status = FileStatus.CHECKED
        file.done_size = file.size
    else:
        file.status = FileStatus.FAILED
    update_root_progress()
    print_root_file()
    return checked


def download_file_simple(file: File, file_path: str):
    """Download a file from Google Drive.

    Args:
        file (File): The file to download.
        file_path (str): The path to save the file.
    """
    request = service.files().get_media(fileId=file.id)
    with open(file_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            file.done_size = status.resumable_progress
            update_root_progress()
            print_root_file()
    file.status = FileStatus.DOWNLOADED


def download_file_with_check(file: File, file_path: str) -> bool:
    """Download a file from Google Drive. Check the integrity of the file.

    Args:
        file (File): The file to download.
        file_path (str): The path to save the file.

    Returns:  
        bool: True if the file is correct, False otherwise.
    """
    download_file_simple(file, file_path)
    return postcheck_file(file, file_path)


def download_file_with_retry(file: File, file_path: str, retry: int) -> bool:
    """Download a file from Google Drive. Retry in case of error.

    Args:
        file (File): The file to download.
        file_path (str): The path to save the file.
        retry (int): The number of retries.

    Returns:
        bool: True if the file is correct, False otherwise.
    """
    if retry == 0:
        return download_file_with_check(file, file_path)

    if download_file_with_check(file, file_path):
        return True
    else:
        return download_file_with_retry(file, file_path, retry - 1)


def download_file(file: File, save_path: str):
    """Download a file from Google Drive.

    Args:
        file (File): The file to download.
        save_path (str): The path to save the file in (ie. the folder).
    """
    global service

    file_path = os.path.join(save_path, file.name)

    # precheck
    exists = os.path.exists(file_path)
    if exists:
        file.status = FileStatus.ALREADY_PRESENT
        file.done_size = file.size
        update_root_progress()
        print_root_file()

    precheck = not config['force'] and (config['check'] or config['retry'] > 0)
    prechecked = False
    if exists and precheck:
        prechecked = precheck_file(file, file_path)

    # download
    if config['force'] or not exists or (not (prechecked and precheck) and config['overwrite']):
        if config['check'] or config['retry'] > 0:
            download_file_with_retry(file, file_path, config['retry'])
        else:
            download_file_simple(file, file_path)


def download_file_recursive(file: File, save_path: str):
    """Download a file from Google Drive.

    Args:
        file (File): The file to download.
        save_path (str, optional): The path to save the file. Defaults to ''.
    """
    file.status = FileStatus.DOWNLOADING
    if file.type == FileType.FOLDER:
        download_folder(file, save_path)
    elif file.type == FileType.FILE:
        download_file(file, save_path)


def main():
    global root_file, status, config

    parse_args()

    status = 'scanning'

    root_file = File(config['file_id'])
    scan_file(root_file)

    if not root_file:
        # TODO: no file found or no permission or ...
        return

    status = 'downloading'
    download_file_recursive(root_file, config['save_path'])

    status = 'done'
    print_root_file()


def scan_file(file: File):
    """Scan a file from Google Drive.

    Args:
        file (File): The file to scan.
    """

    global service

    try:
        # get the file attributes
        response = service.files().get(
            fileId=file.id,
            fields='id,name,mimeType,size,sha256Checksum',
        ).execute()

        # update the file attributes
        file.id = response['id']
        file.name = response['name']
        if 'folder' in response['mimeType']:
            file.type = FileType.FOLDER
            file.size = 0
        else:
            file.type = FileType.FILE
            file.size = int(response['size'])
        file.children = []
        file.done_size = 0
        file.sha256 = response.get('sha256Checksum', '')
        file.status = FileStatus.PENDING

        if file.type == FileType.FOLDER:
            page_token = None
            while True:
                # get the children files
                children_response = service.files().list(
                    q=f"'{file.id}' in parents",
                    spaces="drive",
                    fields="nextPageToken, files(id)",
                    pageToken=page_token,
                ).execute()
                children_files = children_response.get("files", [])

                # scan the children files
                for f in children_files:
                    child_file = File(f['id'])  # pass by reference to update the root file as well
                    file.children.append(child_file)
                    scan_file(child_file)

                # break if there are no more children batch
                page_token = children_response.get("nextPageToken", None)
                if page_token is None:
                    break

            # update the size of the folder
            file.size = sum([child.size for child in file.children])

    except HttpError as error:
        print(f"An error occurred: {error}", flush=True)

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
    units = ['B', 'KB', 'MB', 'GB', 'TB']
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
    # TODO: check progress is between 0 and 1: clip or exception?
    bar = '━' * int(BAR_LENGTH * progress) + ('╾' if progress * BAR_LENGTH % 1 >= 0.5 else '─') + '─' * BAR_LENGTH
    bar = bar[:BAR_LENGTH]
    return f"{bar} {100*progress:.2f}%"


if __name__ == "__main__":
    # file_id = '1GwXP-KpWOxOenOxITTsURJZQ_1pkd4-j' # MEAD
    # file_id = '15UjOIbGJ2NapRG5SD288Zb6nlnY9iTaj'  # test
    main()
