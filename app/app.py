import sys
from enum import IntEnum, unique
from typing import Union

import qtmodern.styles
from PyQt5.Qt import QApplication
from hbutils.model import int_enum_loads

from .widget import AppMainWindow


@int_enum_loads(enable_int=False, name_preprocess=str.upper)
@unique
class AppTheme(IntEnum):
    NOTHING = 0
    LIGHT = 1
    DARK = 2

    @property
    def theme(self):
        if self == self.NOTHING:
            return lambda x: x
        elif self == self.LIGHT:
            return qtmodern.styles.light
        elif self == self.DARK:
            return qtmodern.styles.dark
        else:
            raise ValueError(f'Invalid theme - {repr(self)}.')

    def __call__(self, app: QApplication):
        return self.theme(app)


def run_app(argv=None, theme: Union[str, AppTheme] = 'nothing'):
    app = QApplication(argv or sys.argv)
    AppTheme.loads(theme)(app)

    main_window = AppMainWindow()
    main_window.show()

    sys.exit(app.exec_())

if __name__ == '__main__':
    run_app()