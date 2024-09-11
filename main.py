from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import io
import hashlib


creds = service_account.Credentials.from_service_account_file(
    'key.json',
    scopes=['https://www.googleapis.com/auth/drive']
)
service = build("drive", "v3", credentials=creds)
root_info = None


def update_progress(info):
    if info['type'] == 'folder':
        for child in info['children']:
            update_progress(child)
        if info['size'] == 0:
            info['progress'] = 1
        else:
            info['progress'] = sum([child['progress'] * child['size'] for child in info['children']]) / info['size']


def update_root_progress():
    global root_info
    update_progress(root_info)

def download_folder(info):
    if not os.path.exists(info['path']):
        os.makedirs(info['path'])
    for child in info['children']:
        download_file_recursive(child)
    info['status'] = 'downloaded'


def download_file(info):
    global service
    if os.path.exists(info['path']):
        with open(info['path'], 'rb') as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()
        info['progress'] = 1
        if sha256 == info['sha256']:
            info['status'] = 'done'
        else:
            info['status'] = 'corrupted'
        update_root_progress()
        print_root_info()
        return

    request = service.files().get_media(fileId=info['id'])
    with open(info['path'], 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            info['progress'] = status.progress()
            update_root_progress()
            print_root_info()

    info['status'] = 'downloaded'


def download_file_recursive(info):
    info['status'] = 'downloading'
    if info['type'] == 'folder':
        download_folder(info)
    elif info['type'] == 'file':
        download_file(info)


def main(file_id, save_path=''):
    global root_info
    root_info = get_file_info(file_id, save_path)
    print_root_info()
    if not root_info:
        return

    download_file_recursive(root_info)
    print_root_info()

def download_file_back(file_id, save_path=''):
    creds = service_account.Credentials.from_service_account_file(
        'key.json',
        scopes=['https://www.googleapis.com/auth/drive']
    )

    try:
        service = build("drive", "v3", credentials=creds)
        response = service.files().get(fileId=file_id).execute()
        if response['mimeType'] == 'application/vnd.google-apps.folder':
            folder_path = os.path.join(save_path, response['name'])
            print(f"Downloading: {folder_path}", flush=True)
            os.makedirs(folder_path, exist_ok=True)
            page_token = None
            while True:
                response = (
                    service.files()
                    .list(
                        q=f"'{file_id}' in parents",
                        spaces="drive",
                        fields="nextPageToken, files(id)",
                        pageToken=page_token,
                    )
                    .execute()
                )
                items = response.get("files", [])
                for e in items:
                    download_file_back(e['id'], folder_path)

                page_token = response.get("nextPageToken", None)
                if page_token is None:
                    break
            print(f"Downloaded: {folder_path}", flush=True)

        else:
            progress = 0
            file_path = os.path.join(save_path, response['name'])
            if os.path.exists(file_path):
                print(f"File already exists: {file_path}", flush=True)
                return
            request = service.files().get_media(fileId=file_id)
            fh = io.FileIO(file_path, mode='wb')
            downloader = MediaIoBaseDownload(fh, request)
            print(f"Downloading: {file_path} - {progress:.2f}%", end='', flush=True)

            done = False
            while not done:
                status, done = downloader.next_chunk()
                progress = status.progress() * 100
                print(f"\rDownloading: {file_path} - {progress:.2f}%", end='', flush=True)

            print(f"\rDownloaded: {file_path}", flush=True)

    except HttpError as error:
        print(f"An error occurred: {error}", flush=True)


def get_file_info(file_id, save_path=''):
    info = {}
    # architecture:
    # - id: the id of the file
    # - name: the name of the file
    # - type: the type of the file (folder or file)
    # - children: the children of the file (only for folders)
    # - size: the size of the file
    # - path: the path of the file
    # - sha256: the sha256 of the file
    # - progress: the download progress of the file (0 to 1)
    # - status: the status of the file:
    #   - pending: the file is pending download
    #   - downloading: the file is downloading
    #   - downloaded: the file was already downloaded
    #   - done: the file was already downloaded and the sha256 was checked
    #   - corrupted: the file was already downloaded but the sha256 was not the same

    creds = service_account.Credentials.from_service_account_file(
        'key.json',
        scopes=['https://www.googleapis.com/auth/drive']
    )

    try:
        service = build("drive", "v3", credentials=creds)
        response = service.files().get(fileId=file_id, fields='id,name,mimeType,size,sha256Checksum').execute()

        file_path = os.path.join(save_path, response['name'])

        info = {
            'id': response['id'],
            'name': response['name'],
            'type': 'folder' if 'folder' in response['mimeType'] else 'file',
            'size': int(response.get('size', 0)),
            'path': file_path,
            'children': [],
            'progress': 0,
            'sha256': response.get('sha256Checksum', ''),
            'status': 'pending',
        }
        if info['type'] == 'folder':
            page_token = None
            while True:
                children_response = (
                    service.files()
                    .list(
                        q=f"'{file_id}' in parents",
                        spaces="drive",
                        fields="nextPageToken, files(id)",
                        pageToken=page_token,
                    )
                    .execute()
                )
                children_files = children_response.get("files", [])
                for f in children_files:
                    info['children'].append(get_file_info(f['id'], file_path))

                page_token = children_response.get("nextPageToken", None)
                if page_token is None:
                    break

            info['size'] = sum([child['size'] for child in info['children']])
    except HttpError as error:
        print(f"An error occurred: {error}", flush=True)

    return info


def print_root_info():
    global root_info
    print('\x1b[0;0H\x1b[J', end='', flush=True)
    print_info(root_info)


def print_info(info, indent=''):
    # └├│
    text = indent + f"{info['name']} - {print_size(info['size'])} {print_progress(info['progress'])}"
    print(text, flush=True)
    if indent == '':
        child_indent = ''
    else:
        child_indent = indent[:-2] + ('  ' if indent[-2:] == '└ ' else '│ ')
    if info['progress'] < 1:
        for child_i, child in enumerate(info['children']):
            child_indent_i = '└ ' if child_i == len(info['children']) - 1 else '├ '
            print_info(child, child_indent + child_indent_i)


def print_size(size):
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    return f"{size:.2f} {units[unit]}"


def print_progress(progress):
    # ━╾─
    bar_length = 4
    bar = '━' * int(bar_length * progress) + ('╾' if progress * bar_length % 1 >= 0.5 else '─') + '─' * bar_length
    bar = bar[:bar_length]
    return f"{bar} {100*progress:.2f}%"


if __name__ == "__main__":
    file_id = '1GwXP-KpWOxOenOxITTsURJZQ_1pkd4-j' # MEAD
    save_path = '../AMIGO'
    main(file_id)
