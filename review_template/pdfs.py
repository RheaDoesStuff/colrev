#! /usr/bin/env python
import csv
import json
import logging
import multiprocessing as mp
import os

import git
import pandas as pd
import requests
from bibtexparser.bibdatabase import BibDatabase

from review_template import process
from review_template import repo_setup
from review_template import utils

pdfs_retrieved = 0
existing_pdfs_linked = 0

# https://github.com/ContentMine/getpapers

BATCH_SIZE = repo_setup.config['BATCH_SIZE']


def unpaywall(doi, retry=0, pdfonly=True):

    r = requests.get(
        'https://api.unpaywall.org/v2/{doi}',
        params={'email': repo_setup.config['EMAIL']},
    )

    if r.status_code == 404:
        # print("Invalid/unknown DOI {}".format(doi))
        return None

    if r.status_code == 500:
        # print("Unpaywall API failed. Try: {}/3".format(retry+1))

        if retry < 3:
            return unpaywall(doi, retry+1)
        else:
            # print("Retried 3 times and failed. Giving up")
            return None

    best_loc = None
    try:
        best_loc = r.json()['best_oa_location']
    except json.decoder.JSONDecodeError:
        # print("Response was not json")
        # print(r.text)
        return None
    except KeyError:
        # print("best_oa_location not set")
        # print(r.text)
        return None
    # except:
        # print("Something weird happened")
        # print(r.text)
        #  return None

    if not r.json()['is_oa'] or best_loc is None:
        # print("No OA paper found for {}".format(doi))
        return None

    if(best_loc['url_for_pdf'] is None and pdfonly is True):
        # print("No PDF found..")
        # print(best_loc)
        return None
    else:
        return best_loc['url']

    return best_loc['url_for_pdf']


def is_pdf(path_to_file):

    # TODO: add exceptions
    # try:
    # extract_text(path_to_file)
    return True
    # except:
    #    return False


def acquire_pdf(entry):
    global pdfs_retrieved
    global existing_pdfs_linked
    global missing_entries

    if 'needs_retrieval' != entry.get('pdf_status', 'NA'):
        return entry

    PDF_DIRECTORY = repo_setup.paths['PDF_DIRECTORY']

    if not os.path.exists(PDF_DIRECTORY):
        os.mkdir(PDF_DIRECTORY)

    pdf_filepath = os.path.join(PDF_DIRECTORY, entry['ID'] + '.pdf')

    if os.path.exists(pdf_filepath):
        entry.update(pdf_status='needs_preparation')
        if 'file' not in entry:
            entry.update(file=':' + pdf_filepath + ':PDF')
            existing_pdfs_linked += 1
        return entry

    if 'doi' in entry:
        url = unpaywall(entry['doi'])
        if url is not None:
            if 'Invalid/unknown DOI' not in url:
                res = requests.get(
                    url, headers={
                        'User-Agent': 'Chrome/51.0.2704.103',
                        'referer': 'https://www.doi.org',
                    },
                )
                if 200 == res.status_code:
                    with open(pdf_filepath, 'wb') as f:
                        f.write(res.content)
                    if is_pdf(pdf_filepath):
                        logging.info('Retrieved pdf (unpaywall):'
                                     f' {pdf_filepath}')
                        entry.update(file=':' + pdf_filepath + ':PDF')
                        entry.update('pdf_status', 'needs_preparation')
                        pdfs_retrieved += 1
                    else:
                        os.remove(pdf_filepath)
                else:
                    logging.info('Unpaywall retrieval error '
                                 f'{res.status_code}/{url}')

    if not os.path.exists(pdf_filepath):
        missing_entries.entries.append(entry)

    return entry


def create_commit(repo, db):

    MAIN_REFERENCES = repo_setup.paths['MAIN_REFERENCES']

    utils.save_bib_file(db, MAIN_REFERENCES)

    if 'GIT' == repo_setup.config['PDF_HANDLING']:
        dirname = repo_setup.paths['PDF_DIRECTORY']
        for filepath in os.listdir(dirname):
            if filepath.endswith('.pdf'):
                repo.index.add([os.path.join(dirname, filepath)])

    hook_skipping = 'false'
    if not repo_setup.config['DEBUG_MODE']:
        hook_skipping = 'true'

    if MAIN_REFERENCES not in [i.a_path for i in repo.index.diff(None)] and \
            MAIN_REFERENCES not in [i.a_path for i in repo.head.commit.diff()]:
        logging.info('No new records changed in MAIN_REFERENCES')
        return False
    else:
        repo.index.add([MAIN_REFERENCES])

        processing_report = ''
        if os.path.exists('report.log'):
            with open('report.log') as f:
                processing_report = f.readlines()
            processing_report = \
                f'\nProcessing (batch size: {BATCH_SIZE})\n\n' + \
                ''.join(processing_report)

        repo.index.commit(
            '⚙️ Acquire PDFs ' + utils.get_version_flag() +
            utils.get_commit_report(os.path.basename(__file__)) +
            processing_report,
            author=git.Actor('script:pdfs.py', ''),
            committer=git.Actor(repo_setup.config['GIT_ACTOR'],
                                repo_setup.config['EMAIL']),
            skip_hooks=hook_skipping
        )
        with open('report.log', 'r+') as f:
            f.truncate(0)
        return True


def print_details():
    global pdfs_retrieved
    global existing_pdfs_linked
    global missing_entries

    if existing_pdfs_linked > 0:
        logging.info(
            f'{existing_pdfs_linked} existing PDFs linked in bib file')
    if pdfs_retrieved > 0:
        logging.info(f'{pdfs_retrieved} PDFs retrieved')
    else:
        logging.info('  - No PDFs retrieved')
    if len(missing_entries.entries) > 0:
        logging.info(f'{len(missing_entries.entries)} PDFs missing ')
    return


def export_retrieval_table():
    global missing_entries
    if len(missing_entries.entries) > 0:
        missing_entries_df = pd.DataFrame.from_records(missing_entries.entries)
        col_order = [
            'ID', 'author', 'title', 'journal', 'booktitle',
            'year', 'volume', 'number', 'pages', 'doi'
        ]
        missing_entries_df = missing_entries_df.reindex(col_order, axis=1)
        missing_entries_df.to_csv('missing_pdf_files.csv',
                                  index=False, quoting=csv.QUOTE_ALL)

        logging.info('See missing_pdf_files.csv for paper details')
    return


def acquire_pdfs(db, repo):

    utils.require_clean_repo(repo, ignore_pattern='pdfs/')
    process.check_delay(db, min_status_requirement='processed')

    global missing_entries
    missing_entries = BibDatabase()

    print('TODO: BATCH_SIZE')

    with open('report.log', 'r+') as f:
        f.truncate(0)
    logging.info('Acquire PDFs')

    pool = mp.Pool(repo_setup.config['CPUS'])
    db.entries = pool.map(acquire_pdf, db.entries)
    pool.close()
    pool.join()

    create_commit(repo, db)

    print_details()
    export_retrieval_table()

    return db


def main():

    acquire_pdfs()


if __name__ == '__main__':
    main()