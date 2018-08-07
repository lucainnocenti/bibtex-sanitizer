#!/usr/bin/env python
import argparse
import glob
import os

import arxiv
import bibtexparser

import bibtexsanitizer


def _add_reference_from_arxiv_id(bibfile, arxiv_ids):
    if isinstance(arxiv_ids, str):
        bibtexsanitizer.add_entry_from_arxiv_id(bibfile, arxiv_ids)
    else:
        bibtexsanitizer.add_entries_from_arxiv_ids(bibfile, arxiv_ids)


def _add_reference(bibfile, from_where, ids):
    if from_where == 'arxiv':
        _add_reference_from_arxiv_id(bibfile, ids)
    else:
        raise ValueError('`{}` is not an acceptable command.'.format(from_where))


def _print_reference(from_where, identifier):
    if from_where == 'arxiv':
        print(bibtexsanitizer.get_bibentry_from_arxiv_id(identifier))
    elif from_where == 'doi':
        print(bibtexsanitizer.get_bibentry_from_doi(identifier))
    else:
        raise NotImplementedError('To Be Done.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Manage bib files.')
    parser.add_argument('--bibfile', type=str, default='')
    subparsers = parser.add_subparsers()
    # parser for add reference command
    parser_add = subparsers.add_parser(
        'add', help='Add reference to bibliography.')
    parser_add.add_argument('where', type=str)
    parser_add.add_argument('ids', nargs='*')
    parser_add.add_argument('--action', type=str, default='add')
    # parser for print comments
    parser_print = subparsers.add_parser(
        'print', help='Print to terminal the bibtex entry.')
    parser_print.add_argument('where', type=str)
    parser_print.add_argument('ids', nargs='*')
    parser_print.add_argument('--action', type=str, default='print')
    args = parser.parse_args()
    # decide where to save stuff, if needed
    if not args.bibfile and args.action == 'add':
        bibfiles = glob.glob('./*.bib')
        if not bibfiles:
            raise ValueError(
                'No bib file specified, and none found in the current directory.')
        elif len(bibfiles) > 1:
            raise ValueError('No bib file specified, and more than one found i'
                             'n the current directory, so I do not know which '
                             'one to use.')
        else:
            print('No bib file specified, using {}'.format(bibfiles[0]))
            bibfile = bibfiles[0]
    else:
        bibfile = args.bibfile
    # actually go with the parsing
    if args.action == 'add':
        _add_reference(bibfile, args.where, args.ids)
    elif args.action == 'print':
        _print_reference(args.where, args.ids)
    else:
        raise ValueError('Unknown action.')
