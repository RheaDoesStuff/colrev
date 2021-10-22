#! /usr/bin/env python
import logging
import pprint
import time

import bibtexparser
import dictdiffer
import git

from review_template import repo_setup

logging.getLogger('bibtexparser').setLevel(logging.CRITICAL)


MAIN_REFERENCES = repo_setup.paths['MAIN_REFERENCES']
SCREEN = repo_setup.paths['SCREEN']
DATA = repo_setup.paths['DATA']


def main(citation_key):

    print(f'Trace entry by citation_key: {citation_key}')

    repo = git.Repo()

    revlist = repo.iter_commits()

    pp = pprint.PrettyPrinter(indent=4)

    prev_entry, prev_screen, prev_data = [], '', ''
    for commit in reversed(list(revlist)):
        commit_message_first_line = commit.message.partition('\n')[0]
        print('\n\nCommit: ' +
              f'{commit} - {commit_message_first_line}' +
              f' {commit.author.name} ' +
              time.strftime(
                  '%a, %d %b %Y %H:%M',
                  time.gmtime(commit.committed_date),
              )
              )

        if (MAIN_REFERENCES in commit.tree):
            filecontents = (commit.tree / MAIN_REFERENCES).data_stream.read()
            individual_bib_database = bibtexparser.loads(filecontents)
            entry = [
                entry for entry in individual_bib_database.entries
                if entry['ID'] == citation_key
            ]

            if len(entry) == 0:
                print(f'Entry {citation_key} not in commit.')
            else:
                diffs = list(dictdiffer.diff(prev_entry, entry))
                if len(diffs) > 0:
                    for diff in diffs:
                        pp.pprint(diff)
                prev_entry = entry

        if (SCREEN in commit.tree):
            filecontents = (commit.tree / SCREEN).data_stream.read()
            for line in str(filecontents).split('\\n'):
                if citation_key in line:
                    if line != prev_screen:
                        print(f'Screen: {line}')
                        prev_screen = line

        if (DATA in commit.tree):
            filecontents = (commit.tree / DATA).data_stream.read()
            for line in str(filecontents).split('\\n'):
                if citation_key in line:
                    if line != prev_data:
                        print(f'Data: {line}')
                        prev_data = line

    return


if __name__ == '__main__':
    main()