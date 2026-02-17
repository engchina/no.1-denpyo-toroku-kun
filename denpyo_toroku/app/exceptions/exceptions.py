"""Denpyo Toroku Service の例外定義。

DenpyoServiceError はサービスの各種エラーで送出され、エラー内容・原因・推奨対処を整形して返す。
"""

import os

from denpyo_toroku.app.exceptions.errors import ERR_MESSAGES, ERR_INTERNAL


class DenpyoServiceError(Exception):
    """Denpyo Toroku Service のエラー例外。"""

    def __init__(self, err_num: int, err_params: dict = None) -> None:
        """指定されたエラー番号の例外を送出する。

        Args:
            err_num (int): The error number to raise.
            err_params (dict, optional): The parameters for the error message.
        """
        err_data = ERR_MESSAGES.get(err_num, None)
        if err_data is None:
            self.message = self._format_error_message(
                ERR_INTERNAL,
                params={
                    "error": "不明なエラーコードに対して DenpyoServiceError が送出されました。"
                }
            )
            self.exit_code = 1
        else:
            self.message = self._format_error_message(err_num, err_params)
            self.exit_code = err_data["exit_code"]

        super().__init__(self.message)

    def _format_error_message(self, err_num: int, params: dict) -> str:
        """原因と対処を含めてエラーを整形して返す。

        Args:
            err_num (int): The error number to raise.
            params (dict): The parameters for the error message.

        Returns:
            str: Formatted error message.
        """
        err_id = f"DTS-{str(err_num).rjust(4, '0')}:"
        cause_id = "原因:"
        action_id = "対処:"
        err_data = ERR_MESSAGES[err_num]

        cause_spaces = len(err_id) - len(cause_id)
        if cause_spaces == 0:
            cause_spaces = 1
        action_spaces = len(err_id) - len(action_id)
        if action_spaces == 0:
            action_spaces = 1

        if isinstance(params, dict):
            err_message = err_data["message"].format(**params)
        else:
            err_message = err_data["message"]

        message = (
            f"{err_id} {err_message}\n"
            f"{cause_id}{cause_spaces * ' '} {err_data['cause']}\n"
            f"{action_id}{action_spaces * ' '} {err_data['action']}"
        )
        return message


def get_detailed_exception(e, exc_info_tuple):
    exc_type, _, exc_tb = exc_info_tuple
    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
    msg = "メッセージ: " + str(e) + "~~" + str(exc_type) + "~~" + str(fname) + "~~" + str(exc_tb.tb_lineno)
    return msg
