"""
Method File for the UNI.KN-Bib-Auslastung project
"""

# import necessary libraries
import os
from io import BytesIO, StringIO
import pandas as pd
import imaplib
import email

def extract_csv_attachment(mail, id):
    """
    Extracts the CSV attachment from an email message.

    Args:
        mail (IMAP4): An instance of the IMAP4 class representing the email connection.
        id (bytes): The ID of the email message to extract the attachment from.
    Returns:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment.
        timestamp (str): Timestamp of the email.
        flag (str): Status flag indicating success of the attachment extraction process.
    """
    flag='ok'
    # fetch the email message by ID and parse it into an email object
    _, msg_data = mail.fetch(id, "(RFC822)")
    raw_msg = msg_data[0][1]
    msg = email.message_from_bytes(raw_msg)
        
    # extract timestamp
    timestamp = pd.to_datetime(msg['Date']).tz_localize(None).replace(second=0) 
    df_data = None
    
    # loop through the email parts to find the CSV attachment and read it into a DataFrame
    for part in msg.walk():
        filename = part.get_filename()
        if filename and filename.lower().endswith('.csv'):
            payload = part.get_payload(decode=True)
            df_data = pd.read_csv(BytesIO(payload), delimiter=',', skiprows=8, on_bad_lines='skip')
    
    # check if a CSV attachment was found and set the flag accordingly       
    if df_data is None:
        flag = 'no csv attachment in email found'
              
    return df_data, timestamp, flag


def read_email():
    """
    Reads the most recent email (last 24h) with a sender filter and extracts the 
    CSV attachment as a DataFrame.

    Returns:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment.
        timestamp (str): Timestamp of the email.
        flag (str): Status flag indicating success of the email reading process.
    """
    # Connect to the email server and log in
    try:
        server = os.environ.get("SERVER")
        port = int(os.environ.get('PORT'))

        if port == 993:
            mail = imaplib.IMAP4_SSL(server, port)
        else:
            mail = imaplib.IMAP4(server, port)
            mail.starttls()
        mail.login(os.getenv("USER"), os.getenv("PASSWORD"))
        mail.select("INBOX")
        
    except Exception as e:
        flag = f'Error connecting to email server, {e}'
        return None, None, flag

    # Search for emails from specific sender sent in the last 24 hours
    since_date = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime('%d-%b-%Y')
    _, data = mail.search(None, '(ALL FROM "{}" SINCE {})'.format(os.getenv("SENDER"), since_date))
    mail_ids = data[0].split()

    # extract csv attachment
    if mail_ids: 
        return extract_csv_attachment(mail, mail_ids[-1])
    
    else:
        flag = 'no email found'
        return None, None, flag
 
    
def preprocess_data(df_data):
    """ 
    Preprocesses the extracted DataFrame by removing unnecessary columns 
    and summing up the Average Number of Users and Peak Number of Users 
    for each AP Name.
    
    Args:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment.
    Returns:
        df_data (DataFrame): Preprocessed DataFrame with unnecessary columns removed 
            and summed up user numbers.
        flag (str): Status flag indicating success of the preprocessing process.
    """
    flag = 'ok'
    
    # remove column Radio Type if it exists
    if 'Radio Type' in df_data.columns:
        df_data = df_data.drop(columns=['Radio Type'])
    else:
        flag = 'column Radio Type not found'
        
    # remove column AP MACAddress if it exists
    if 'AP MACAddress' in df_data.columns:
        df_data = df_data.drop(columns=['AP MACAddress'])
    else:
        flag = flag + ' and column AP MACAddress not found' if flag != 'ok' else 'column AP MACAddress not found'
        
    # add columns Average Number of Users and Peak Number of Users if they have the same AP Name
    if 'AP Name' in df_data.columns and 'Average Number of Users' in df_data.columns and 'Peak Number of Users' in df_data.columns:
        df_data['Average Number of Users'] = df_data.groupby('AP Name')['Average Number of Users'].transform('sum')
        df_data['Peak Number of Users'] = df_data.groupby('AP Name')['Peak Number of Users'].transform('sum')
        df_data = df_data.drop_duplicates(subset=['AP Name'])
        df_data = df_data.reset_index(drop=True)
    else:
        flag = flag + ' and necessary columns for summing up not found' if flag != 'ok' else 'necessary columns for summing up not found'
        
    return df_data, flag


def map_router_to_location(df_data):
    """ 
    Maps the router names in the DataFrame to their corresponding locations using a CSV file 
    containing the mapping information.
    
    Args:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment.
    Returns:
        df_data (DataFrame): DataFrame with an additional column for the mapped locations.
        flag (str): Status flag indicating success or failure of the mapping process.
    """
    flag = 'ok'
    
    # load mapping from environment variable and create a DataFrame
    mapping_str = os.getenv("MAPPING")
    if mapping_str:
        router_map = pd.read_csv(StringIO(mapping_str), sep=';')
    else:
        flag = 'No mapping found in environment'
        return df_data, flag
    
    # map router names to locations using the csv file
    router_area_map = dict(zip(router_map.iloc[:, 1].astype(str).str.strip(), router_map.iloc[:, 2].astype(str).str.strip()))
    
    # add new column to df_data with its location
    df_data['AP Name'] = df_data['AP Name'].astype(str).str.strip()
    df_data['Location'] = df_data['AP Name'].map(router_area_map)

    # check if there are any AP Names that could not be mapped to a location
    unmapped_aps = df_data[df_data['Location'].isna()]['AP Name'].unique()
    if len(unmapped_aps) > 0:
        flag = 'the following AP Names could not be mapped to a location: ' + ', '.join(unmapped_aps)
            
    # check if there are any AP Names in MAPPING that are not in the df_data
    missing_aps = set(router_area_map.keys()) - set(df_data['AP Name'])
    if len(missing_aps) > 0:
        flag = flag + ' and the following AP Names from the mapping file are not in the data: ' + ', '.join(missing_aps) if flag != 'ok' else 'the following AP Names from the mapping file are not in the data: ' + ', '.join(missing_aps)
            
    return df_data, flag


def calc_occupancy(df_data):
    """
    Calculate the occupancy for each location based on the average number of users 
    and the capacity defined in the capacity map.

    Args:
        df_data (DataFrame): DataFrame containing the data from the CSV attachment 
            with mapped locations.
        capacity_map (dict): Dictionary mapping locations to their capacities.
    Returns:
        occup (dict): Dictionary containing the occupancy for each location.
    """
    flag = 'ok'
    
    # load capacity map from environment variable and create a dictionary
    capacity_str = os.getenv("CAPACITY")
    if capacity_str:
        capacity_map = pd.read_csv(StringIO(capacity_str), sep=';')
    else:
        flag = 'No capacity data found in environment'
        return {}, flag
    capacity_map = dict(zip(capacity_map.iloc[:, 0].astype(str).str.strip(), capacity_map.iloc[:, 1].astype(float)))
    
    occup = {}
    
    # calculate occupancy for each location based on the average number of users
    for loc in capacity_map.keys():
        if loc in df_data['Location'].values:
            avg_users = df_data[df_data['Location'] == loc]['Average Number of Users'].sum()
            capacity = capacity_map[loc]
            if capacity > 0:
                occupancy = min(avg_users * capacity, 1) * 100
            else:
                occupancy = 0
            occup[loc] = occupancy
        else:
            flag = flag + f' and location {loc} not found in data' if flag != 'ok' else f'location {loc} not found in data'
            occup[loc] = 0
            
    # filter occupancy dictionary
    occup = {k: v for k, v in occup.items() if k not in ['nf', 'na']}
            
    return occup, flag


def save_as_csv(occupancy, path, time):
    """ 
    Save occupancy values to a csv file. 
    
    Args:
        occupancy (dict): Dictionary containing the occupancy for each location.
        path (str): Path to save the csv.
        time (str): Timestamp from data.
    """
    
    # save occupancy values to a csv file
    occ_df = pd.DataFrame(list(occupancy.items()), columns=['Location', 'Occupancy'])
    occ_df.to_csv(path, index=False)
    
    # append timestamp to the csv file
    with open(path, 'a') as f:
        f.write(f"timestamp,{time}\n")