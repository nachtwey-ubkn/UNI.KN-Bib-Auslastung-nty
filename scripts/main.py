"""
Main File for the UNI.KN-Bib-Auslastung project used in the action workflow
"""

# import necessary libraries
import os
from dotenv import load_dotenv
from methods import read_email, preprocess_data, map_router_to_location, calc_occupancy, save_as_csv    

# only for local execution
load_dotenv()

# define flags for each step of the process
flags = ['not read', 'not processed', 'not mapped', 'not calculated']

# read data and create figure
df_data, timestamp, flags[0] = read_email()

if flags[0] == 'ok':
    df_data, flags[1] = preprocess_data(df_data)

if flags[1] == 'ok':
    df_data, flags[2] = map_router_to_location(df_data)
    
if flags[2] != 'No mapping found in environment':
    occ, flags[3] = calc_occupancy(df_data)
    
if flags[3] == 'ok':
    path = os.path.join(os.getcwd(), 'docs/temp/oc_values.csv')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_as_csv(occ, path, timestamp)

# return error message if any of the flags is not 'ok'
if any(flag != 'ok' for flag in flags):
    error_message = 'Error in processing: ' + '; '.join([str(flag) for flag in flags if flag != 'ok'])
    print(error_message)