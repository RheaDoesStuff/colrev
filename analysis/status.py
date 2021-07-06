#! /usr/bin/env python
import os

import config
import pandas as pd
import utils

nr_duplicates_hash_ids = 0
nr_entries_added = 0
nr_current_entries = 0

MAIN_REFERENCES = config.paths['SCREEN']
SCREEN = config.paths['SCREEN']
DATA = config.paths['SCREEN']
SEARCH_DETAILS = config.paths['SEARCH_DETAILS']


def validate_files():
    print('todo: implement validation')
    return


if __name__ == '__main__':

    print('')
    print('')

    print('Status')
    validate_files()
    print('')

    if not os.path.exists(MAIN_REFERENCES):
        print(' ┌ Search')
        print(' |  - Not yet initiated')
    else:
        # Search
        bib_database = utils.load_references_bib(
            modification_check=False,
            initialize=False,
        )

        search_details = pd.read_csv(
            SEARCH_DETAILS, dtype=str,
        )
        search_details['number_records'] = \
            search_details['number_records'].astype(int)

        print(' ┌ Search')
        print(
            ' |  - total retrieved: ' +
            str(search_details['number_records'].sum()).rjust(7, ' '),
        )
        print(' |  - merged: ' + str(len(bib_database.entries)).rjust(16, ' '))
        print(' |')

        # Screen
        if not os.path.exists(SCREEN):
            print(' ┌ Screen')
            print(' |  - Not yet initiated')
        else:

            screen = pd.read_csv(SCREEN, dtype=str)
            print(' ├ Screen 1')
            print(' |  - total: ' + str(len(screen)).rjust(17, ' '))
            print(
                ' |  - excluded: ' +
                str(len(screen[screen['inclusion_1'] == 'no'])).rjust(14, ' '),
            )
            print(
                ' |  - included: ' +
                str(len(screen[screen['inclusion_1'] == 'yes']))
                .rjust(14, ' '),
            )
            if 0 != len(screen[screen['inclusion_1'] == 'TODO']):
                print(
                    ' |  - TODO: ' + str(
                        len(
                            screen.drop(
                                screen[screen['inclusion_1'] != 'TODO'].index,
                            ),
                        ),
                    ).rjust(18, ' '),
                )
            print(' |')

            screen.drop(
                screen[
                    screen['inclusion_1']
                    == 'no'
                ].index, inplace=True,
            )
            print(' ├ Screen 2')
            print(' |  - total: ' + str(len(screen)).rjust(17, ' '))
            print(
                ' |  - excluded: ' +
                str(len(screen[screen['inclusion_2'] == 'no'])).rjust(14, ' '),
            )
            print(
                ' |  - included: ' +
                str(len(screen[screen['inclusion_2'] == 'yes']))
                .rjust(14, ' '),
            )
            if 0 != len(screen[screen['inclusion_2'] == 'TODO']):
                print(
                    ' |  - TODO: ' +
                    str(len(screen[screen['inclusion_2'] == 'TODO']))
                    .rjust(18, ' '),
                )
            print(' |')

            # Data
            if not os.path.exists(DATA):
                print(' ├ Data')
                print(' |  - Not yet initiated')
            else:
                data = pd.read_csv(DATA, dtype=str)
                print(' ├ Data extraction')
                print(' |  - total: ' + str(len(data)).rjust(17, ' '))
                if 0 != len(screen[screen['inclusion_2'] == 'yes'])-len(data):
                    print(
                        ' |  - IMPORT FROM SCREEN: ' +
                        str(len(
                            screen[screen['inclusion_2'] == 'yes'])-len(data))
                        .rjust(4, ' '),
                    )

                print('')
                print('')
