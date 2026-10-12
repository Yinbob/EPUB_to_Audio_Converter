"""Gradio 5 与新版 Starlette 的状态码名称兼容。"""


def configure_gradio_status_compat():
    from starlette import status

    # 新版通过 __getattr__ 读取旧名称，每次队列轮询都会发出弃用警告。
    # 两个名称均表示 422；显式别名避开动态读取，不屏蔽其他警告。
    old_name = "HTTP_422_UNPROCESSABLE_ENTITY"
    new_name = "HTTP_422_UNPROCESSABLE_CONTENT"
    values = vars(status)
    if old_name not in values and new_name in values:
        setattr(status, old_name, values[new_name])
