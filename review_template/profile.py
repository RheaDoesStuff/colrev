#! /usr/bin/env python
import os

import numpy as np
import pandas as pd

from review_template import repo_setup
from review_template import utils


def main():

    print('\n\nSample profile\n')

    bib_database = utils.load_references_bib(
        modification_check=False,
        initialize=False,
    )

    if not os.path.exists('output'):
        os.mkdir('output')

    references = pd.DataFrame.from_dict(bib_database.entries)
    references.rename(columns={'ID': 'citation_key'}, inplace=True)

    references['outlet'] = np.where(~references['journal'].isnull(),
                                    references['journal'],
                                    references['booktitle'])

    references = references[['citation_key',
                             'ENTRYTYPE',
                             'author',
                             'title',
                             'journal',
                             'booktitle',
                             'outlet',
                             'year',
                             'volume',
                             'number',
                             'pages',
                             'doi',
                             ]]

    SCREEN = repo_setup.paths['SCREEN']
    screen = pd.read_csv(SCREEN, dtype=str)
    DATA = repo_setup.paths['SCREEN']
    data = pd.read_csv(DATA, dtype=str)

    observations = \
        references[references['citation_key'].isin(
            screen[screen['inclusion_2'] == 'yes']['citation_key'].tolist()
        )]

    missing_outlet = observations[observations['outlet'].isnull(
    )]['citation_key'].tolist()
    print(f'No outlet: {missing_outlet}')

    observations = pd.merge(observations, data, how='left', on='citation_key')

    observations.to_csv('output/sample.csv', index=False)
    # print(observations.crosstab)
    tabulated = pd.pivot_table(observations[['outlet', 'year']],
                               index=['outlet'],
                               columns=['year'],
                               aggfunc=len,
                               fill_value=0,
                               margins=True)
    tabulated.to_csv('output/journals_years.csv')

    tabulated = pd.pivot_table(observations[['ENTRYTYPE', 'year']],
                               index=['ENTRYTYPE'],
                               columns=['year'],
                               aggfunc=len,
                               fill_value=0,
                               margins=True)
    tabulated.to_csv('output/ENTRYTYPES.csv')

    return


if __name__ == '__main__':
    main()