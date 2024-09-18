# gddload

```manpage
usage: gddload [-h] [--save_path SAVE_PATH] [--check] [--overwrite] [--force] [--retry RETRY] file_id

Download files from Google Drive

positional arguments:
  file_id               The Google Drive file ID

options:
  -h, --help            show this help message and exit
  --save_path SAVE_PATH
                        The path to save the files
  --check               Check the sha256 of the files before and after download
  --overwrite           Overwrite the file if it already exists. If used with --check, only files that are corrupted will be overwritten
  --force               Force the download of the file even if it already exists
  --retry RETRY         The number of retries in case of error. (implies --check)
```