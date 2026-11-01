import os
import tkinter as tk
from tkinter import filedialog, messagebox

import requests

UPLOAD_URL = "http://127.0.0.1:5000/upload"


def choose_and_upload():
    # 隐藏 tkinter 主窗口，只保留文件对话框
    root = tk.Tk()
    root.withdraw()

    paths = filedialog.askopenfilenames(
        title="选择要上传的文件",
        filetypes=[("所有文件", "*.*")]
    )
    if not paths:
        print("未选择文件")
        return

    for path in paths:
        name = os.path.basename(path)
        try:
            with open(path, "rb") as f:
                resp = requests.post(
                    UPLOAD_URL,
                    files={"file": (name, f)},
                    timeout=60
                )
            resp.raise_for_status()
            print(f"上传成功：{name}")
        except Exception as e:
            print(f"上传失败：{name} -> {e}")

    messagebox.showinfo("完成", "处理完毕")


if __name__ == "__main__":
    choose_and_upload()