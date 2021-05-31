#! /usr/bin/env python
import logging
import os
import time

import bibtexparser
import dictdiffer
import git
import utils
from bibtexparser.customization import convert_to_unicode

logging.getLogger('bibtexparser').setLevel(logging.CRITICAL)


def trace_hash(bibfilename, hash_id_needed):
    global nr_found

    with open(bibfilename) as bibtex_file:
        bib_database = bibtexparser.bparser.BibTexParser(
            customization=convert_to_unicode, common_strings=True,
        ).parse_file(bibtex_file, partial=True)

        for entry in bib_database.entries:
            if utils.create_hash(entry) == hash_id_needed:
                print(
                    '\n\n Found hash ',
                    hash_id_needed,
                    '\n in ',
                    bibfilename,
                    '\n\n',
                )
                print(entry)
                nr_found += 1
    return


if __name__ == '__main__':

    print('')
    print('')

    print('Trace entry by citation_key')

    citation_key = input('provide citation_key')
#    citation_key = 'Blijleven2019'

    os.chdir('data')

    repo = git.Repo()

    # TODO: trace_hash and list individual search results

    path = 'references.bib'

    revlist = (
        (commit, (commit.tree / path).data_stream.read())
        for commit in repo.iter_commits(paths=path)
    )
    prev_entry = []

    for commit, filecontents in reversed(list(revlist)):
        print('----------------------------------')
        individual_bib_database = bibtexparser.loads(filecontents)
        entry = [
            entry for entry in individual_bib_database.entries
            if entry['ID'] == citation_key
        ]
        if len(entry) != 0:
            print(
                str(commit),
                ' - ',
                commit.message.replace('\n', ''),
                ' ',
                commit.author.name,
                ' ',
                time.strftime(
                    '%a, %d %b %Y %H:%M',
                    time.gmtime(commit.committed_date),
                ),
            )
            for diff in list(dictdiffer.diff(prev_entry, entry)):
                print(diff)
            prev_entry = entry

    path = 'screen.csv'

    revlist = (
        (commit, (commit.tree / path).data_stream.read())
        for commit in repo.iter_commits(paths=path)
    )

    for commit, filecontents in reversed(list(revlist)):
        print('----------------------------------')
        print(
            str(commit),
            ' - ',
            commit.message.replace('\n', ''),
            ' ',
            commit.author.name,
            ' ',
            time.strftime(
                '%a, %d %b %Y %H:%M',
                time.gmtime(commit.committed_date),
            ),
        )
        for line in str(filecontents).split('\\n'):
            if citation_key in line:
                print(line)

    path = 'data.csv'

    revlist = (
        (commit, (commit.tree / path).data_stream.read())
        for commit in repo.iter_commits(paths=path)
    )

    for commit, filecontents in reversed(list(revlist)):
        print('----------------------------------')
        print(
            str(commit),
            ' - ',
            commit.message.replace('\n', ''),
            ' ',
            commit.author.name,
            ' ',
            time.strftime(
                '%a, %d %b %Y %H:%M',
                time.gmtime(commit.committed_date),
            ),
        )
        for line in str(filecontents).split('\\n'):
            if citation_key in line:
                print(line)