#! /usr/bin/env python
import collections
import json
import logging
import multiprocessing as mp
import os
import re
import sys
import time
import urllib

import git
import requests
from Levenshtein import ratio
from nameparser import HumanName

from review_template import dedupe
from review_template import process
from review_template import repo_setup
from review_template import utils

BATCH_SIZE = repo_setup.config['BATCH_SIZE']

prepared, need_manual_prep = 0, 0

current_batch_counter = mp.Value('i', 0)


def correct_entrytype(entry):

    conf_strings = [
        'proceedings',
        'conference',
    ]

    for i, row in LOCAL_CONFERENCE_ABBREVIATIONS.iterrows():
        conf_strings.append(row['abbreviation'].lower())
        conf_strings.append(row['conference'].lower())

    # Consistency checks
    if 'journal' in entry:
        if any(
            conf_string in entry['journal'].lower()
            for conf_string in conf_strings
        ):
            # print('WARNING: conference string in journal field: ',
            #       entry['ID'],
            #       entry['journal'])
            entry.update(booktitle=entry['journal'])
            entry.update(ENTRYTYPE='inproceedings')
            del entry['journal']
    if 'booktitle' in entry:
        if any(
            conf_string in entry['booktitle'].lower()
            for conf_string in conf_strings
        ):
            entry.update(ENTRYTYPE='inproceedings')

    if 'dissertation' in entry.get('fulltext', 'NA').lower() and \
            entry['ENTRYTYPE'] != 'phdthesis':
        prior_e_type = entry['ENTRYTYPE']
        entry.update(ENTRYTYPE='phdthesis')
        logging.info(f'Set {entry["ID"]} from {prior_e_type} to phdthesis '
                     'because the fulltext link contains "dissertation"')
        # TODO: if school is not set: using named entity recognition or
        # following links: detect the school and set the field

    if 'thesis' in entry.get('fulltext', 'NA').lower() and \
            entry['ENTRYTYPE'] != 'phdthesis':
        prior_e_type = entry['ENTRYTYPE']
        entry.update(ENTRYTYPE='phdthesis')
        logging.info(f'Set {entry["ID"]} from {prior_e_type} to phdthesis '
                     'because the fulltext link contains "thesis"')
        # TODO: if school is not set: using named entity recognition or
        # following links: detect the school and set the field

    # TODO: create a warning if any conference strings (ecis, icis, ..)
    # as stored in CONFERENCE_ABBREVIATIONS is in an article/book

    # Journal articles should not have booktitles/series set.
    if 'article' == entry['ENTRYTYPE']:
        if 'booktitle' in entry:
            if 'journal' not in entry:
                entry.update(journal=entry['booktitle'])
                del entry['booktitle']
        if 'series' in entry:
            if 'journal' not in entry:
                entry.update(journal=entry['series'])
                del entry['series']

    if 'book' == entry['ENTRYTYPE']:
        if 'series' in entry:
            if any(
                conf_string in entry['series'].lower()
                for conf_string in conf_strings
            ):
                conf_name = entry['series']
                del entry['series']
                entry.update(booktitle=conf_name)
                entry.update(ENTRYTYPE='inproceedings')

    if 'article' == entry['ENTRYTYPE']:
        if 'journal' not in entry:
            if 'series' in entry:
                journal_string = entry['series']
                entry.update(journal=journal_string)
                del entry['series']

    return entry


def homogenize_entry(entry):

    fields_to_process = [
        'author', 'year', 'title',
        'journal', 'booktitle', 'series',
        'volume', 'number', 'pages', 'doi',
        'abstract'
    ]
    for field in fields_to_process:
        if field in entry:
            entry[field] = entry[field].replace('\n', ' ')\
                .rstrip()\
                .lstrip()\
                .replace('{', '')\
                .replace('}', '')

    if 'author' in entry:
        # DBLP appends identifiers to non-unique authors
        entry.update(author=str(re.sub(r'[0-9]{4}', '', entry['author'])))

        # fix name format
        if (1 == len(entry['author'].split(' ')[0])) or \
                (', ' not in entry['author']):
            entry.update(author=utils.format_author_field(entry['author']))

    if 'title' in entry:
        entry.update(title=re.sub(r'\s+', ' ', entry['title']).rstrip('.'))
        entry.update(title=utils.title_if_mostly_upper_case(entry['title']))

    if 'booktitle' in entry:
        entry.update(booktitle=utils.title_if_mostly_upper_case(
            entry['booktitle']))

        stripped_btitle = re.sub(r'\d{4}', '', entry['booktitle'])
        stripped_btitle = re.sub(r'\d{1,2}th', '', stripped_btitle)
        stripped_btitle = re.sub(r'\d{1,2}nd', '', stripped_btitle)
        stripped_btitle = re.sub(r'\d{1,2}rd', '', stripped_btitle)
        stripped_btitle = re.sub(r'\d{1,2}st', '', stripped_btitle)
        stripped_btitle = re.sub(r'\([A-Z]{3,6}\)', '', stripped_btitle)
        stripped_btitle = stripped_btitle\
            .replace('Proceedings of the', '')\
            .replace('Proceedings', '')
        entry.update(booktitle=stripped_btitle)

    if 'journal' in entry:
        entry.update(
            journal=utils.title_if_mostly_upper_case(entry['journal']))

    if 'pages' in entry:
        entry.update(pages=utils.unify_pages_field(entry['pages']))

    if 'doi' in entry:
        entry.update(doi=entry['doi'].replace('http://dx.doi.org/', ''))

    if 'issue' in entry and 'number' not in entry:
        entry.update(number=entry['issue'])
        del entry['issue']

    return entry


LOCAL_JOURNAL_ABBREVIATIONS, \
    LOCAL_JOURNAL_VARIATIONS, \
    LOCAL_CONFERENCE_ABBREVIATIONS = \
    utils.retrieve_local_resources()


def apply_local_rules(entry):

    if 'journal' in entry:
        for i, row in LOCAL_JOURNAL_ABBREVIATIONS.iterrows():
            if row['abbreviation'].lower() == entry['journal'].lower():
                entry.update(journal=row['journal'])

        for i, row in LOCAL_JOURNAL_VARIATIONS.iterrows():
            if row['variation'].lower() == entry['journal'].lower():
                entry.update(journal=row['journal'])

    if 'booktitle' in entry:
        for i, row in LOCAL_CONFERENCE_ABBREVIATIONS.iterrows():
            if row['abbreviation'].lower() == entry['booktitle'].lower():
                entry.update(booktitle=row['conference'])

    return entry


CR_JOURNAL_ABBREVIATIONS, \
    CR_JOURNAL_VARIATIONS, \
    CR_CONFERENCE_ABBREVIATIONS = \
    utils.retrieve_crowd_resources()


def apply_crowd_rules(entry):

    if 'journal' in entry:
        for i, row in CR_JOURNAL_ABBREVIATIONS.iterrows():
            if row['abbreviation'].lower() == entry['journal'].lower():
                entry.update(journal=row['journal'])

        for i, row in CR_JOURNAL_VARIATIONS.iterrows():
            if row['variation'].lower() == entry['journal'].lower():
                entry.update(journal=row['journal'])

    if 'booktitle' in entry:
        for i, row in CR_CONFERENCE_ABBREVIATIONS.iterrows():
            if row['abbreviation'].lower() == entry['booktitle'].lower():
                entry.update(booktitle=row['conference'])

    return entry


def crossref_query(entry):
    # https://github.com/CrossRef/rest-api-doc
    api_url = 'https://api.crossref.org/works?'
    params = {'rows': '5', 'query.bibliographic': entry['title']}
    url = api_url + urllib.parse.urlencode(params)
    headers = {'user-agent':
               f'prepare.py (mailto:{repo_setup.config["EMAIL"]})'}
    ret = requests.get(url, headers=headers)
    if ret.status_code != 200:
        return

    data = json.loads(ret.text)
    items = data['message']['items']
    most_similar = {
        'crossref_title': '',
        'similarity': 0,
        'doi': '',
    }
    for item in items:
        if 'title' not in item:
            continue

        # TODO: author
        try:
            title_similarity = ratio(
                item['title'].pop().lower(),
                entry['title'].lower(),
            )
            # TODO: could also be a proceedings paper...
            container_similarity = ratio(
                item['container-title'].pop().lower(),
                entry['journal'].lower(),
            )
            weights = [0.6, 0.4]
            similarities = [title_similarity, container_similarity]

            similarity = sum(similarities[g] * weights[g]
                             for g in range(len(similarities)))

            result = {
                'similarity': similarity,
                'doi': item['DOI'],
            }
            if most_similar['similarity'] < result['similarity']:
                most_similar = result
        except KeyError:
            pass

    time.sleep(1)
    return {'success': True, 'result': most_similar}


def get_doi_from_crossref(entry):
    if ('title' not in entry) or ('doi' in entry):
        return entry

    MAX_RETRIES_ON_ERROR = 3
    # https://github.com/OpenAPC/openapc-de/blob/master/python/import_dois.py
    if len(entry['title']) > 60 and 'doi' not in entry:
        try:
            ret = crossref_query(entry)
            retries = 0
            while not ret['success'] and retries < MAX_RETRIES_ON_ERROR:
                retries += 1
                ret = crossref_query(entry)
            if ret['result']['similarity'] > 0.95:
                entry.update(doi=ret['result']['doi'])
        except KeyboardInterrupt:
            sys.exit()
    return entry


def get_dblp_venue(venue_string):
    venue = venue_string
    api_url = 'https://dblp.org/search/venue/api?q='
    url = api_url + venue_string.replace(' ', '+') + '&format=json'
    headers = {'user-agent':
               f'prepare.py (mailto:{repo_setup.config["EMAIL"]})'}
    ret = requests.get(url, headers=headers)

    data = json.loads(ret.text)
    venue = data['result']['hits']['hit'][0]['info']['venue']
    re.sub(r' \(.*?\)', '', venue)

    return venue


def get_metadata_from_dblp(entry):
    if 'doi' in entry:
        return entry

    api_url = 'https://dblp.org/search/publ/api?q='
    url = api_url + entry.get('title', '').replace(' ', '+') + '&format=json'
    # print(url)
    headers = {'user-agent':
               f'prepare.py (mailto:{repo_setup.config["EMAIL"]})'}
    ret = requests.get(url, headers=headers)

    try:

        data = json.loads(ret.text)
        items = data['result']['hits']['hit']
        item = items[0]['info']

        author_string = ' and '.join([author['text']
                                     for author in item['authors']['author']])
        author_string = utils.format_author_field(author_string)

        author_similarity = ratio(
            dedupe.format_authors_string(author_string),
            dedupe.format_authors_string(entry['author']),
        )
        title_similarity = ratio(
            item['title'].lower(),
            entry['title'].lower(),
        )
        # container_similarity = ratio(
        #     item['venue'].lower(),
        #     utils.get_container_title(entry).lower(),
        # )
        year_similarity = ratio(
            item['year'],
            entry['year'],
        )
        # print(f'author_similarity: {author_similarity}')
        # print(f'title_similarity: {title_similarity}')
        # print(f'container_similarity: {container_similarity}')
        # print(f'year_similarity: {year_similarity}')

        weights = [0.4, 0.3, 0.3]
        similarities = [title_similarity, author_similarity, year_similarity]

        similarity = sum(similarities[g] * weights[g]
                         for g in range(len(similarities)))
        # print(similarity)
        if similarity > 0.99:
            if 'Journal Articles' == item['type']:
                entry['ENTRYTYPE'] = 'article'
                entry['journal'] = get_dblp_venue(item['venue'])
                entry['volume'] = item['volume']
                entry['number'] = item['number']
            if 'Conference and Workshop Papers' == item['type']:
                entry['ENTRYTYPE'] = 'inproceedings'
                entry['booktitle'] = get_dblp_venue(item['venue'])
            if 'doi' in item:
                entry['doi'] = item['doi']
            entry['dblp_key'] = 'https://dblp.org/rec' + item['key']
    except KeyError:
        pass
    except UnicodeEncodeError:
        logging.error(
            'UnicodeEncodeError - this needs to be fixed at some time')
        pass

    return entry


# https://www.crossref.org/blog/dois-and-matching-regular-expressions/
doi_regex = re.compile(r'10\.\d{4,9}/[-._;/:A-Za-z0-9]*')


def get_doi_from_links(entry):
    if 'doi' in entry:
        return entry

    url = ''
    url = entry.get('url', entry.get('fulltext', ''))
    if url != '':
        try:
            r = requests.get(url)
            res = re.findall(doi_regex, r.text)
            if res:
                if len(res) == 1:
                    ret_doi = res[0]
                    entry['doi'] = ret_doi
                else:
                    counter = collections.Counter(res)
                    ret_doi = counter.most_common(1)[0][0]
                    entry['doi'] = ret_doi

                # print('  - TODO: retrieve meta-data and valdiate, '
                #       'especially if multiple dois matched')
                doi_entry = {'doi': entry['doi'], 'ID': entry['ID']}
                doi_entry = retrieve_doi_metadata(doi_entry)
                if dedupe.get_entry_similarity(entry.copy(), doi_entry) < 0.95:
                    del entry['doi']

                logging.info('Added doi from website: ' + entry['doi'])

        except requests.exceptions.ConnectionError:
            return entry
            pass
        except Exception as e:
            print(e)
            return entry
            pass
    return entry


def doi2json(doi):
    url = 'http://dx.doi.org/' + doi
    headers = {'accept': 'application/vnd.citationstyles.csl+json'}
    r = requests.get(url, headers=headers)
    return r.text


def retrieve_doi_metadata(entry):
    # for testing:
    # curl -iL -H "accept: application/vnd.citationstyles.csl+json"
    # -H "Content-Type: application/json" http://dx.doi.org/10.1111/joop.12368

    if 'doi' not in entry:
        return entry

    # For exceptions:
    orig_entry = entry.copy()

    try:
        full_data = doi2json(entry['doi'])
        retrieved_record = json.loads(full_data)
        author_string = ''
        for author in retrieved_record.get('author', ''):
            if 'family' not in author:
                continue
            if '' != author_string:
                author_string = author_string + ' and '
            author_given = author.get('given', '')
            # Use local given name when no given name is provided by doi
            if '' == author_given:
                authors = entry['author'].split(' and ')
                local_author_string = [x for x in authors
                                       if author.get('family', '').lower()
                                       in x.lower()]
                local_author = HumanName(local_author_string.pop())

                author_string = author_string + \
                    author.get('family', '') + ', ' + \
                    local_author.first + ' ' + local_author.middle
                # Note: if there is an exception, use:
                # author_string = author_string + \
                # author.get('family', '')
            else:
                author_string = author_string + \
                    author.get('family', '') + ', ' + \
                    author.get('given', '')

        if not author_string == '':
            if utils.mostly_upper_case(author_string
                                       .replace(' and ', '')
                                       .replace('Jr', '')):

                names = author_string.split(' and ')
                entry.update(author='')
                for name in names:
                    # Note: https://github.com/derek73/python-nameparser
                    # is very effective (maybe not perfect)
                    parsed_name = HumanName(name)
                    parsed_name.string_format = \
                        '{last} {suffix}, {first} ({nickname}) {middle}'
                    parsed_name.capitalize(force=True)
                    entry.update(author=entry['author'] + ' and ' +
                                 str(parsed_name).replace(' , ', ', '))
                if entry['author'].startswith(' and '):
                    entry.update(author=entry['author'][5:]
                                 .rstrip()
                                 .replace('  ', ' '))
            else:
                entry.update(author=str(
                    author_string).rstrip().replace('  ', ' '))

        retrieved_title = retrieved_record.get('title', '')
        if not retrieved_title == '':
            entry.update(title=re.sub(r'\s+', ' ', str(retrieved_title))
                         .replace('\n', ' '))
        try:
            if 'published-print' in retrieved_record:
                date_parts = \
                    retrieved_record['published-print']['date-parts']
                entry.update(year=str(date_parts[0][0]))
            elif 'published-online' in retrieved_record:
                date_parts = \
                    retrieved_record['published-online']['date-parts']
                entry.update(year=str(date_parts[0][0]))
        except KeyError:
            pass

        retrieved_pages = retrieved_record.get('page', '')
        if retrieved_pages != '':
            # DOI data often has only the first page.
            if not entry.get('pages', 'no_pages') in retrieved_pages \
                    and '-' in retrieved_pages:
                entry.update(pages=utils.unify_pages_field(
                    str(retrieved_pages)))
        retrieved_volume = retrieved_record.get('volume', '')
        if not retrieved_volume == '':
            entry.update(volume=str(retrieved_volume))

        retrieved_issue = retrieved_record.get('issue', '')
        if not retrieved_issue == '':
            entry.update(number=str(retrieved_issue))

        retrieved_container_title = \
            str(retrieved_record.get('container-title', ''))
        if not retrieved_container_title == '':
            if 'journal' in entry:
                entry.update(journal=retrieved_container_title)
            elif 'booktitle' in entry:
                entry.update(booktitle=retrieved_container_title)
            elif 'series' in entry:
                entry.update(series=retrieved_container_title)

            # if 'series' in entry:
            #     if entry['series'] != retrieved_container_title:
            #             entry.update(series=retrieved_container_title)

        if 'abstract' not in entry:
            retrieved_abstract = retrieved_record.get('abstract', '')
            if not retrieved_abstract == '':

                retrieved_abstract = \
                    re.sub(
                        r'<\/?jats\:[^>]*>',
                        ' ',
                        retrieved_abstract,
                    )
                retrieved_abstract = \
                    re.sub(r'\s+', ' ', retrieved_abstract)
                entry.update(abstract=str(retrieved_abstract).replace('\n', '')
                             .lstrip().rstrip())
    except IndexError:
        logging.error(f'Index error (authors?) for {entry["ID"]}')
        return orig_entry
        pass
    except json.decoder.JSONDecodeError:
        logging.error(f'DOI retrieval error: {entry.get("ID", "NO_ID")}'
                      f' / {entry["doi"]}')
        return orig_entry
        pass
    except TypeError:
        logging.error(f'Type error: : {entry["ID"]}')
        return orig_entry
        pass
    except requests.exceptions.ConnectionError:
        logging.error(f'ConnectionError: : {entry["ID"]}')
        return orig_entry
        pass

    entry['complete_based_on_doi'] = 'True'

    return entry


# Based on https://en.wikipedia.org/wiki/BibTeX
entry_field_requirements = \
    {'article': ['author', 'title', 'journal', 'year', 'volume', 'issue'],
     'inproceedings': ['author', 'title', 'booktitle', 'year'],
     'incollection': ['author', 'title', 'booktitle', 'publisher', 'year'],
     'inbook': ['author', 'title', 'chapter', 'publisher', 'year'],
     'book': ['author', 'title', 'publisher', 'year'],
     'phdthesis': ['author', 'title', 'school', 'year'],
     'masterthesis': ['author', 'title', 'school', 'year'],
     'techreport': ['author', 'title', 'institution', 'year'],
     'unpublished': ['title', 'author', 'year']}

# book, inbook: author <- editor


def is_complete(entry):
    sufficiently_complete = False

    if entry['ENTRYTYPE'] in entry_field_requirements.keys():
        reqs = entry_field_requirements[entry['ENTRYTYPE']]
        if all(x in entry for x in reqs):
            sufficiently_complete = True
    else:
        logging.info(f'No field requirements set for {entry["ENTRYTYPE"]}')

    return sufficiently_complete


def is_doi_complete(entry):
    # Note: complete_based_on_doi is set at the end of retrieve_doi_metadata
    return 'True' == entry.get('complete_based_on_doi', 'NA')


entry_field_inconsistencies = \
    {'article': ['booktitle'],
     'inproceedings': ['volume', 'issue', 'number', 'journal'],
     'incollection': [],
     'inbook': ['journal'],
     'book': ['volume', 'issue', 'number', 'journal'],
     'phdthesis': ['volume', 'issue', 'number', 'journal', 'booktitle'],
     'masterthesis': ['volume', 'issue', 'number', 'journal', 'booktitle'],
     'techreport': ['volume', 'issue', 'number', 'journal', 'booktitle'],
     'unpublished': ['volume', 'issue', 'number', 'journal', 'booktitle']}


def has_inconsistent_fields(entry):
    found_inconsistencies = False

    if entry['ENTRYTYPE'] in entry_field_inconsistencies.keys():
        incons_fields = entry_field_inconsistencies[entry['ENTRYTYPE']]
        inconsistencies = [x for x in incons_fields if x in entry]
        if inconsistencies:
            logging.warning(f'Inconsistency in {entry["ID"]}:'
                            f' {entry["ENTRYTYPE"]} '
                            f'with {inconsistencies} field(s).')
            found_inconsistencies = True
    else:
        logging.info(f'No fields inconsistencies set for {entry["ENTRYTYPE"]}')

    return found_inconsistencies


def has_incomplete_fields(entry):

    if entry.get('title', '').endswith('...') or \
            entry.get('title', '').endswith('…') or \
            entry.get('journal', '').endswith('...') or \
            entry.get('journal', '').endswith('…') or \
            entry.get('booktitle', '').endswith('...') or \
            entry.get('booktitle', '').endswith('…') or \
            entry.get('author', '').endswith('...') or \
            entry.get('author', '').endswith('…') or \
            entry.get('author', '').endswith('and others'):
        return True
    return False


fields_to_keep = [
    'ID', 'ENTRYTYPE',
    'author', 'year', 'title',
    'journal', 'booktitle', 'series',
    'volume', 'number', 'pages', 'doi',
    'abstract', 'school',
    'editor', 'book-group-author',
    'book-author', 'keywords', 'file',
    'status', 'fulltext', 'entry_link',
    'dblp_key'
]
fields_to_drop = [
    'type', 'url', 'organization',
    'issn', 'isbn', 'note', 'issue',
    'unique-id', 'month', 'researcherid-numbers',
    'orcid-numbers', 'eissn', 'article-number',
    'publisher', 'author_keywords', 'source',
    'affiliation', 'document_type', 'art_number',
    'address', 'language', 'doc-delivery-number',
    'da', 'usage-count-last-180-days', 'usage-count-since-2013',
    'doc-delivery-number', 'research-areas',
    'web-of-science-categories', 'number-of-cited-references',
    'times-cited', 'journal-iso', 'oa', 'keywords-plus',
    'funding-text', 'funding-acknowledgement', 'day',
    'related', 'bibsource', 'timestamp', 'biburl',
    'complete_based_on_doi'
]


def drop_fields(entry):
    for key in list(entry):
        if 'NA' == entry[key]:
            del entry[key]
        if(key not in fields_to_keep):
            # drop all fields not in fields_to_keep
            entry.pop(key)
            # warn if fields are dropped that are not in fields_to_drop
            if key not in fields_to_drop:
                logging.info(f'Dropped {key} field')
    return entry


def prepare(entry):
    global current_batch_counter

    if 'imported' != entry['status']:
        return entry

    with current_batch_counter.get_lock():
        if current_batch_counter.value >= BATCH_SIZE:
            return entry
        else:
            current_batch_counter.value += 1

    entry = correct_entrytype(entry)

    entry = homogenize_entry(entry)

    entry = apply_local_rules(entry)

    entry = apply_crowd_rules(entry)

    entry = get_doi_from_crossref(entry)

    entry = get_metadata_from_dblp(entry)

    entry = get_doi_from_links(entry)

    entry = retrieve_doi_metadata(entry)

    if (is_complete(entry) or is_doi_complete(entry)) and \
            not has_inconsistent_fields(entry) and \
            not has_incomplete_fields(entry):
        entry = drop_fields(entry)
        # logging.info(f'Successfully prepared {entry["ID"]}')
        entry.update(status='prepared')
    else:
        if 'complete_based_on_doi' in entry:
            del entry['complete_based_on_doi']
        logging.info(f'Manual preparation needed for {entry["ID"]}')
        entry.update(status='needs_manual_preparation')

    return entry


def create_commit(r, bib_database):
    global prepared
    global need_manual_prep

    MAIN_REFERENCES = repo_setup.paths['MAIN_REFERENCES']

    utils.save_bib_file(bib_database, MAIN_REFERENCES)

    if MAIN_REFERENCES in [item.a_path for item in r.index.diff(None)] or \
            MAIN_REFERENCES in r.untracked_files:

        r.index.add([MAIN_REFERENCES])

        processing_report = ''
        if os.path.exists('report.log'):
            with open('report.log') as f:
                processing_report = f.readlines()
            processing_report = \
                f'\nProcessing (batch size: {BATCH_SIZE})\n' + \
                f'- Prepared {prepared} entries\n' + \
                f'- Marked {need_manual_prep} entries ' + \
                'for manual preparation' + \
                '\n- Details:\n' + ''.join(processing_report)

        r.index.commit(
            '⚙️ Prepare ' + MAIN_REFERENCES + utils.get_version_flag() +
            utils.get_commit_report(os.path.basename(__file__)) +
            processing_report,
            author=git.Actor('script:prepare.py', ''),
            committer=git.Actor(repo_setup.config['GIT_ACTOR'],
                                repo_setup.config['EMAIL']),
        )
        logging.info('Created commit')
        print()
        with open('report.log', 'r+') as f:
            f.truncate(0)
        return True
    else:
        logging.info('No additional prepared entries available')
        return False


def prepare_entries(db, repo):
    global prepared
    global need_manual_prep

    process.check_delay(db, min_status_requirement='imported')
    with open('report.log', 'r+') as f:
        f.truncate(0)

    logging.info('Prepare')

    in_process = True
    while in_process:
        with current_batch_counter.get_lock():
            current_batch_counter.value = 0  # start new batch

        prepared = len([x for x in db.entries
                        if 'prepared' == x.get('status', 'NA')])
        need_manual_prep = \
            len([x for x in db.entries
                if 'needs_manual_preparation' == x.get('status', 'NA')])

        pool = mp.Pool(repo_setup.config['CPUS'])
        db.entries = pool.map(prepare, db.entries)
        pool.close()
        pool.join()

        prepared = len([x for x in db.entries
                        if 'prepared' == x.get('status', 'NA')]) - prepared
        need_manual_prep = \
            len([x for x in db.entries
                if 'needs_manual_preparation' == x.get('status', 'NA')]) \
            - need_manual_prep

        in_process = create_commit(repo, db)

    print()

    return db