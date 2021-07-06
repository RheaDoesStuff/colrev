#! /usr/bin/env python
import config
import utils

MAIN_REFERENCES = config.paths['MAIN_REFERENCES']

if __name__ == '__main__':

    print('')
    print('')

    print('Reformat bibliography')

    bib_database = utils.load_references_bib(
        modification_check=True, initialize=False,
    )

    utils.save_bib_file(bib_database, MAIN_REFERENCES)
