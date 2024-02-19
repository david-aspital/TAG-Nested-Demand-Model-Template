import pandas as pd
import numpy as np
import os
import tempfile
import datetime


def export_list(layout, filename=None, folderpath=None):
    '''Export list to the given path as attribute file
    Parameters
    ----------
    layout : str
        The layout file name (incuding extension). If no extension is provided, .llax will be assumed.
    filename : str, path object, optional
        The filename of the exported .att file. By default it is the same as the name of the .llax file.
    folderpath : str, path object, optional
        The folder path of the export location. By default it is the same folder as the Visum .ver file
    '''
    if filename is None:
        filename = layout

    if folderpath is None:
        folderpath = os.path.dirname(Visum.IO.CurrentVersionFile)

    name, ext = os.path.splitext(layout)
    if not (ext == '.llax' or ext == '.lla'):
        layout += '.llax'

    name, ext = os.path.splitext(filename)
    if ext != 'att':
        name += '.att'
    
    Visum.IO.SaveAttributeFile(os.path.join(folderpath, name), layout, 9)


def create_data_frame(visum_list=None, layout=None, temp_path=tempfile.gettempdir(), folderpath=None):
    '''Create pandas df from Visum list by exporting as .att to temp path and reading back as df
    Parameters
    ----------
    visum_list : obj, optional
        The Visum list object (including all columns to be exported). Either layout or this variable needs to be provided.
    layout : str, optional
        The layout file name (incuding extension). If no extension is provided, .llax will be assumed. Either visum_list or this variable needs to be provided.
    temp_path : str, path object, optional
        The folder path of the temporary location to write attribute data to. By default this is the %TMP% location
    folderpath : str, path object, optional
        The folder path of the layout file. By default it is the same folder as the Visum .ver file
    Returns
    ----------
    DataFrame
    '''

    if (visum_list is None) and (layout is None):
        raise ValueError("Either visum_list or layout need to be defined.")

    if folderpath is None:
        folderpath = os.path.dirname(Visum.IO.CurrentVersionFile)

    if not (layout is None):
        name, ext = os.path.splitext(layout)
        if not (ext == '.llax' or ext == '.lla'):
            layout += '.llax'
        filepath = os.path.join(folderpath, layout)
        temp_file = f"{name}.att"
        export_list(filepath, temp_file, temp_path)
    else:
        temp_file = f'visum_list_{datetime.datetime.now().strftime("%d-%m-%Y_%H-%M-%S")}.att'
        visum_list.SaveToAttributeFile(os.path.join(temp_path, temp_file), 9)
    data_frame = pd.read_csv(os.path.join(temp_path, temp_file), sep="\t", header=2, skiprows=10)
    return data_frame

def export_att_file(df, folder, filename, visum_object, id_col):
    # Export pandas df as .att file that can be ready into Visum
    att_header = '''$VISION
* {}
* {}
* 
* Table: Version block
* 
$VERSION:VERSNR	FILETYPE	LANGUAGE	UNIT
11	Att	ENG	KM

* 
* Table: {}s
* 
'''

    # Check for extension 
    if filename[-4:] == ".att":
        pass
    else:
        filename = filename+".att"

    # Check Visum object
    objects = ['NODE', 'LINK', 'TURN', 'ZONE', 'CONNECTOR', 'MAINNODE', 'MAINTURN', 'MAINZONE']
    visum_object = visum_object.upper()
    if visum_object in objects:
        pass
    else:
        raise KeyError("'"+visum_object+"'"+" is not a valid object.")

    headers = df.columns.values.tolist()
    headers = ["$"+visum_object+":NO" if x==id_col else x for x in headers]

    # Write .att header
    with open (folder+r"\\"+filename,'w') as o:
        o.write(att_header.format(os.getlogin(), datetime.datetime.now(), visum_object.title()))
        o.close()
        # Write dataframe
        df.to_csv(folder+r"\\"+filename, mode='a', header=headers, sep="\t", index=False)



temp_path = tempfile.gettempdir()

# Step 1: Get list of matrices
mat_list = Visum.Lists.CreateMatrixList
cols = ['NO', 'CODE', 'NAME', 'DSTRATCODE', 'PERSONGROUPCODE', 'ACTPAIR']
for col in cols:
    mat_list.AddColumn(col)
df_mats = create_data_frame(visum_list=mat_list, temp_path=temp_path)

# Step 2: Get numbers of HB demand matrices
dstrata_list = Visum.Lists.CreateDemandStratumList
cols = ['CODE', 'PERSONGROUPCODES', 'ACTIVITYPAIRCODE', r'ACTPAIR\HB', 'DEMANDMODELCODE']
for col in cols:
    dstrata_list.AddColumn(col)
df_dstrata = create_data_frame(visum_list=dstrata_list, temp_path=temp_path)
df_hb_dstrata = df_dstrata.loc[df_dstrata['ACTPAIR\HB']==1]
hb_dstrata = df_hb_dstrata['$DEMANDSTRATUM:CODE'].tolist()
mat_cond = list(zip(hb_dstrata, df_hb_dstrata.DEMANDMODELCODE.tolist(), ["Demand"]*20))


df_hb_mats = df_mats.loc[df_mats[['DSTRATCODE', 'ACTPAIR', "Dimension"]].apply(tuple, axis=1).isin(mat_cond)]
hb_dstrata_dict = dict(zip(df_hb_mats.DSTRATCODE, df_hb_mats['$MATRIX:NO']))

# Step 3: Get NHB trip rates
tbl_entries = Visum.Lists.CreateTableEntryList
tbl_entries.SetObjects('NHB Trip Rates')
cols = ['NO', 'HB_ACTPAIR', 'NHB_ACTPAIR', 'PERSONGROUP', 'TRIPRATE']
for col in cols:
    tbl_entries.AddColumn(col)
df_nhb_rates = create_data_frame(visum_list=tbl_entries, temp_path=temp_path)

# Step 4: Loop over HB demand strata and calculate column sums + multiply by trip rates
nhb_prods = pd.DataFrame(None, columns=['Zone', 'DemandStratum', 'Productions'])
for hds in hb_dstrata:
    # get mat number
    mat_no = hb_dstrata_dict[hds]
    # get matrix col sums
    col_sums = Visum.Net.Zones.GetMultiAttValues(f'MATCOLSUM({mat_no})')
    col_sums = pd.DataFrame(col_sums, columns=['Zone', hds])
    actpair = hds.split("_")[0]
    pgroup = hds.split("_", 1)[1]
    values = []
    for nhb in ['NHBEB', 'NHBO']:
        col_sums[f'{nhb}_{pgroup}'] = col_sums[hds]*df_nhb_rates.loc[(df_nhb_rates.HB_ACTPAIR==actpair)&(df_nhb_rates.NHB_ACTPAIR==nhb)&(df_nhb_rates.PERSONGROUP==pgroup)].TRIPRATE.squeeze()
        values.append(f'{nhb}_{pgroup}')
    col_sums_out = col_sums.melt(id_vars='Zone', value_vars=values, var_name='DemandStratum', value_name='Productions')
    nhb_prods = nhb_prods.append(col_sums_out[['Zone', 'DemandStratum', 'Productions']])

# Step 5: Sum over HB purposes
nhb_prods = nhb_prods.groupby(['Zone', 'DemandStratum'], as_index=False).Productions.sum()
nhb_prods['VisumAtt'] = "PRODUCTION(" + nhb_prods.DemandStratum + ")"
nhb_prods = nhb_prods.pivot_table(index='Zone', values='Productions', columns='VisumAtt', aggfunc=np.sum, fill_value=0).reset_index()

# Step 6: Read back into Visum
now = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
export_att_file(nhb_prods, temp_path, f'NHB_Prods_{now}.att', 'Zone', 'Zone')
Visum.IO.LoadAttributeFile(f"{temp_path}\\NHB_Prods_{now}.att")
