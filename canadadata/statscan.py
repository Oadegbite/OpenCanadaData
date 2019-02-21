import numpy as np
import pandas as pd
from .io import unzip_data


def optimize_statscan(statscan_data: pd.DataFrame):
    statscan_data.Element = statscan_data.Element.astype('category')


CONTROL_COLS = ['VECTOR', 'COORDINATE', 'DECIMALS',
                'STATUS', 'SYMBOL', 'TERMINATED',
                'SCALAR_FACTOR','SCALAR_ID', 'DGUID', 'UOM', 'UOM_ID']
STATSCAN_TYPES = {'Age group' : 'category',
                  'Sex': 'category',
                  'UOM': 'category',
                  'UOM_ID': 'category',
                  'GEO': 'category',
                  'SCALAR_FACTOR': 'category',
                  'SCALAR_ID' : 'category',
                  'STATUS' : 'category',
                  'SYMBOL' : 'category'}


def read_statscan_csv(statcan_fn: str):
    return pd.read_csv(statcan_fn, dtype=STATSCAN_TYPES, low_memory=False)


def to_wide_format(statscan_data: pd.DataFrame, pivot_column):
    """
    Converts statscan data to wide format
    :param statscan_data:
    :return: a dataframe with the statscan data converted to wide format
    """
    base = statscan_data.copy()
    group_cols = [col for col in base.columns.tolist()
                    if col not in CONTROL_COLS + [pivot_column, 'VALUE']]
    # Assign a group number
    base['group'] = base.groupby(group_cols).ngroup()

    # Pivot on the group, turning the element into columns
    values = base.pivot_table(index='group',
                              columns=pivot_column,
                              values='VALUE',
                              aggfunc=np.max,
                              dropna=False)
    # Drop Element and VALUE columns and drop duplicates
    base = base.drop(columns=[pivot_column, 'VALUE']).drop_duplicates(subset=group_cols)
    # Now merge with values
    return base.merge(values, on='group').drop(columns='group')


class StatscanDataset(object):

    def __init__(self, url: str, pivot_column: str):
        self.url = url
        self.pivot_column = pivot_column

    def get_data(self, cache_dir='.', wide=False, index_col: str = None, drop_control_cols=True):
        files = unzip_data(self.url, cache_dir)
        data = read_statscan_csv(files[0])
        if wide:
            data = to_wide_format(data, pivot_column=self.pivot_column)
        if index_col:
            data = data.set_index(index_col)

        if drop_control_cols:
            drop_cols = [col for col in CONTROL_COLS if col in data.columns]
            data = data.drop(columns=drop_cols)
        return data

    def get_wide_data(self, cache_dir='.', index_col: str = None, drop_control_cols=True):
        return self.get_data(cache_dir=cache_dir, wide=True, index_col=index_col, drop_control_cols=drop_control_cols)


class StatscanDatasetMetadata(object):

    def __init__(self, meta_df: pd.DataFrame):
        self.cube_info = meta_df.head(1).set_index('Cube Title')

        note_row = meta_df[meta_df['Cube Title'] == 'Note ID'].index.item()
        correction_row = meta_df[meta_df['Cube Title'] == 'Correction ID'].index.item()

        self.note = meta_df.iloc[note_row + 1:correction_row, 0:2]
        self.note.columns = ['Note ID', 'Note']
        self.note = self.note.set_index('Note ID')

        dimension2_row = meta_df[meta_df['Cube Title'] == 'Dimension ID'].tail(1).index.item()
        self.dimensions = meta_df.iloc[2:dimension2_row, 0:4]
        self.dimensions.columns = ['Dimension ID', 'Dimension name', 'Dimension Notes', 'Dimension Definitions']
        self.dimensions = self.dimensions.set_index('Dimension ID')

        self.dimensions['Dimension Notes'] = self.dimensions['Dimension Notes'].map(self.note['Note'])

        symbol_row = meta_df[meta_df['Cube Title'] == 'Symbol Legend'].index.item()
        self.dimension_details = meta_df.iloc[dimension2_row + 1:symbol_row, 0:8]
        self.dimension_details.columns = ['Dimension ID', 'Member Name', 'Classification Code', 'Member ID',
                                   'Parent Member ID',
                                   'Terminated', 'Member Notes', 'Member Definitions']
        self.dimension_details = self.dimension_details.set_index('Dimension ID')

        survey_row = meta_df[meta_df['Cube Title'] == 'Survey Code'].index.item()
        self.survey = meta_df.iloc[survey_row + 1:survey_row + 2, 0:2]
        self.survey.columns = ['Survey Code', 'Survey Name']
        self.survey = self.survey.set_index('Survey Code')

        subject_row = meta_df[meta_df['Cube Title'] == 'Subject Code'].index.item()
        self.subject = meta_df.iloc[subject_row + 1:subject_row + 2, 0:2]
        self.subject.columns = ['Subject Code', 'Subject Name']
        self.subject = self.subject.set_index('Subject Code')



