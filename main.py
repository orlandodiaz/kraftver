#!/usr/bin/env python3
"""Main file"""
# Kraftver is a simple Flask webserver to which you can upload an Warcraft III
# map (in .w3c and .w3x formats) and get the map data back as a JSON response.

import uuid
import os
import json
import shutil
import subprocess
import sys
import config

from flask import Flask, request
from werkzeug.utils import secure_filename

KRAFTVER = Flask(__name__)
KRAFTVER.config['MAX_CONTENT_LENGTH'] = config.MAX_MAP_SIZE * 1024 * 1024

def read_map(file_name, unpack_dir_name):
    """Reads the map name from the supplied file and returns data about it."""
    map_name = ""
    map_flags = ""

    with open(file_name, "rb") as map_file:
        # Read the map name, map name is stored from 9th byte until the \x00.
        map_file.seek(8)

        # while our byte isn't zero, read the bytes and convert them to text
        byte = map_file.read(1)
        while byte != b'\x00':
            try:
                map_name += byte.decode('utf-8')
            except UnicodeDecodeError:  # probably utf8 char so we need 1 more byte
                byte += map_file.read(1)
                map_name += byte.decode('utf-8')

            byte = map_file.read(1)

        # Read the flags from the w3x header and transform them to a string
        # of ones and zeros
        for i in range(4):
            byte = map_file.read(1)
            byte = ord(byte)
            byte = bin(byte)[2:].rjust(8, '0')
            for bit in byte:
                map_flags += str(bit)

        # read the max players number
        max_player_num = map_file.read(4)
        max_player_num = int.from_bytes(max_player_num, byteorder='little')

    # Extract the MPQ archive from the map file
    try:
        extract_map_file(file_name, unpack_dir_name)
    except ValueError as e:
        raise ValueError(e)

    # Reads the tileset from the file

    if is_valid_w3e(unpack_dir_name + '/war3map.w3e'):
        with open(unpack_dir_name + '/war3map.w3e', "rb") as f:
            # 9nth byte contains the tileset
            main_tileset = f.read(9)
            main_tileset = main_tileset[-1]
            main_tileset = str(chr(main_tileset))

            # Determine the tileset from the char
            if main_tileset == 'A':
                main_tileset = "Ashenvale"
            elif main_tileset == 'B':
                main_tileset = "Barrens"
            elif main_tileset == 'C':
                main_tileset = "Felwood"
            elif main_tileset == 'D':
                main_tileset = "Dungeon"
            elif main_tileset == 'F':
                main_tileset = "Lordaeron Fall"
            elif main_tileset == 'G':
                main_tileset = "Underground"
            elif main_tileset == 'L':
                main_tileset = "Lordaeron Summer"
            elif main_tileset == 'N':
                main_tileset = "Northend"
            elif main_tileset == 'Q':
                main_tileset = "Village Fall"
            elif main_tileset == 'V':
                main_tileset = "Village"
            elif main_tileset == 'W':
                main_tileset = "Lordaeron Winter"
            elif main_tileset == 'X':
                main_tileset = "Dalaran"
            elif main_tileset == 'Y':
                main_tileset = "Cityscape"
            elif main_tileset == 'Z':
                main_tileset = "Sunken Ruins"
            elif main_tileset == 'I':
                main_tileset = "Icecrown"
            elif main_tileset == 'J':
                main_tileset = "Dalaran Ruins"
            elif main_tileset == 'O':
                main_tileset = "Outland"
            elif main_tileset == 'K':
                main_tileset = "Black Citadel"
            else:
                main_tileset = "Unknown (bug?): " + main_tileset
    else:
        raise ValueError("doesn't contain a valid .w3e file")

    map_data = {
        "map_name": map_name,
        "map_flags": map_flags,
        "max_players": max_player_num,
        "tileset": main_tileset
    }

    return map_data


def valid_map(file_name):
    """
    Checks if the magic numbers of a given file correspond to a
    Warcraft III map file
    """
    with open(file_name, "rb") as f:
        map_name_bytes = f.read(4)

    try:
        map_name_bytes = str(map_name_bytes.decode('utf-8'))
    except UnicodeDecodeError:
        return False

    if map_name_bytes == "HM3W":
        return True

    return False


def map_error(error_string, file):
    """
    Returns a simple dictionary explaining the error during the map
    reading process, to be used as a JSON response
    """
    response = {
        "success": False,
        "error": str(error_string),
        "map_name": None,
        "map_flags": None,
        "max_players": None,
        "tileset": None,
        "file_name": secure_filename(file.filename)
    }

    return response


def extract_map_file(file_name, unpack_dir_name):
    """Extracts the given file name via the mpq-extract external tool."""
    try:
        os.mkdir(unpack_dir_name)
    except FileExistsError:
        shutil.rmtree(unpack_dir_name)
        os.mkdir(unpack_dir_name)

    # Construct the extract shell command
    extract_command = ("cd %s && mpq-extract -e %s &>/dev/null") % \
                      (unpack_dir_name.replace(" ", "\\ "),
                       file_name.replace(" ", "\\ "))
    # We need to escape the command because it may contain ' (or spacec like
    # above) which can confuse the shell
    extract_command = extract_command.replace("'", "\\'")
    extract_command = extract_command.replace("(", "\\(")
    extract_command = extract_command.replace(")", "\\)")

    # Call the external mpq-extract tool to extract the map
    extract_shell = subprocess.Popen(extract_command,
                                     shell=True,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
    extract_std = extract_shell.communicate()

    if extract_shell.returncode != 0:  # can't extract the map file properly
        raise ValueError("can't extract the map file properly: " \
                         + str(extract_std[1].decode("utf-8")))

    # Get the list of all physical files extracted by the mpq-extract tool
    archive_files = sorted(os.listdir(unpack_dir_name))

    # Sometimes mpg-extract doesn't extract anything at all and remains silent
    #  about it
    if len(archive_files) == 0:
        raise ValueError("external tool didn't extract anything")

    # And sometimes mpg-extract extracts one empty file, a valid map should
    # contain at least 16 files inside
    if len(archive_files) < 16:
        raise ValueError("external tool didn't extract properly")

    # Rename extracted files according to the data in listfile
    # The last file is usually attributes and the file before the last
    # file is listfile
    os.rename(unpack_dir_name + '/' + archive_files[-2],
              unpack_dir_name + '/listfile')
    os.rename(unpack_dir_name + '/' + archive_files[-1],
              unpack_dir_name + '/attributes')

    # But sometimes listfile may be the last file, we need to check if our
    # listfile is correct and rename a bit differently if the attributes and
    # the listfile were swapped in the map file

    if not is_valid_list_file(unpack_dir_name + '/listfile') and \
        is_valid_list_file(unpack_dir_name + '/attributes'):
        print("Note: Listfile and attributes file were swapped in this map \
        file. Renaming accordingly.")
        os.rename(unpack_dir_name + '/attributes',
                  unpack_dir_name + '/correctlistfile')
        os.rename(unpack_dir_name + '/listfile',
                  unpack_dir_name + '/attributes')
        os.rename(unpack_dir_name + '/correctlistfile',
                  unpack_dir_name + '/listfile')
    elif not is_valid_list_file(unpack_dir_name + '/listfile') \
         and not is_valid_list_file(unpack_dir_name + '/attributes'):
        raise ValueError("can't find valid listfile inside the map file")

    # We renamed the listfile and attributes file successfully so we remove
    # them from the list
    archive_files = archive_files[:-2]

    # We read the listfile into the list array
    list_file = []
    with open(unpack_dir_name + '/listfile', 'r') as f:
        for line in f:
            list_file.append(line.replace('\n', ''))

    # We check if the files listed in the listfile actually exist in the MPQ
    # archive or was the archive "protected" by removing some files.
    if len(list_file) != len(archive_files):
        print("Note: Number of files listed in the listfile (" +
              str(len(list_file)) + ") do not match the number of physical \
              files (" + str(len(archive_files)) + ").")
        print("Note: The map may have been \"protected\". Continuing but may \
        encounter errors.")

    # We rename the files according to the listfile
    number_of_files = len(archive_files) - 1

    while number_of_files > -1:
        # archive_files contains regular filenames in the directory
        # (file00000.xxx, for example) list_file contains filenames from the
        # listfile (war3map.doo for example)
        genericfilename = unpack_dir_name + '/' + archive_files[number_of_files]
        listfilename = unpack_dir_name + '/' + list_file[number_of_files]
        os.rename(genericfilename, listfilename)

        # The archive can also contain subdirectories so we need to recreate
        # the subdirs and move files into it
        if len(list_file[number_of_files].split('\\')) > 1:
            path = ''

            for subdir in list_file[number_of_files].split('\\')[:-1]:
                path += subdir + '/'

            os.makedirs(unpack_dir_name + '/' + path, exist_ok=True)  # Recreate the subdir

            # .datadir/'AoW\Images\TGA\BTNRessAuraIcon.tga' bellow
            filenamewithslashes = unpack_dir_name + '/' + list_file[number_of_files]
            # .datadir/AoW/Images/TGA/'BTNRessAuraIcon.tga' bellow
            filenameinsubdir = unpack_dir_name + '/' + path + \
            list_file[number_of_files].split('\\')[-1]

            shutil.move(filenamewithslashes, filenameinsubdir)

        number_of_files -= 1

    return True


def is_valid_w3e(file_path):
    with open(file_path, "rb") as f:
        main_tileset_sig = f.read(4)

    main_tileset_sig = str(main_tileset_sig.decode('utf-8'))

    if main_tileset_sig == "W3E!":
        return True
    else:
        print("Invalid w3e file", file_path)
        return False


def is_valid_list_file(list_file_path):
    """
    Checks if a given filename is a valid listfile. We read the listfile and
    check if any of the lines contain names such as war3map.w3i, war3map.wts
    or war3map.shd. If they do, it's a valid listfile.
    """
    with open(list_file_path, 'r') as f:
        try:
            listfile_data = f.readlines()
        except UnicodeDecodeError:  # prob. binary file, not a listfile
            return False

        if "war3map.w3i\n" in listfile_data or "war3map.wts\n" \
            in listfile_data or "war3map.shd\n" in listfile_data:
            return True
        else:
            return False


@KRAFTVER.route('/', methods=['POST'])
def route():
    """Accepts map, reads it and returns found data."""
    file_name = "/tmp/kraftver-" + str(uuid.uuid1())
    unpack_dir_name = file_name + "-data"
    f = request.files['map']
    f.save(file_name)

    # Check if we didn't receive an empty file
    if os.stat(file_name).st_size == 0:
        os.remove(file_name)
        shutil.rmtree(unpack_dir_name)
        return json.dumps(map_error("empty map file", f), sort_keys=True,
                          indent=4) + '\n'

    # Check if the uploaded file is a valid wc3 map
    if not valid_map(file_name):
        os.remove(file_name)
        shutil.rmtree(unpack_dir_name)
        return json.dumps(map_error("invalid map file", f), sort_keys=True,
                          indent=4) + '\n'

    # Try to read the map
    try:
        map_data = read_map(file_name, unpack_dir_name)
    except Exception as e:
        os.remove(file_name)
        shutil.rmtree(unpack_dir_name)
        return json.dumps(map_error("can't process map file: " + str(e), f),
                          sort_keys=True, indent=4) + '\n'

    os.remove(file_name)
    shutil.rmtree(unpack_dir_name)

    # Return the data
    response = {
        "success": True,
        "error": None,
        "map_name": map_data['map_name'],
        "map_flags": map_data['map_flags'],
        "max_players": map_data['max_players'],
        "tileset": map_data['tileset'],
        "file_name": secure_filename(f.filename)
    }
    return json.dumps(response, sort_keys=True, indent=4) + '\n'

if __name__ == "__main__":
    KRAFTVER.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
