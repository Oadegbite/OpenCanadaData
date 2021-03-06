import numpy as np
import pandas as pd
import os
import re
from .repo import Repo
import logging

logger = logging.getLogger("ocandata")


def optimize_statscan(statscan_data: pd.DataFrame):
    statscan_data.Element = statscan_data.Element.astype("category")


CONTROL_COLS = [
    "VECTOR",
    "COORDINATE",
    "DECIMALS",
    "STATUS",
    "SYMBOL",
    "TERMINATED",
    "SCALAR_FACTOR",
    "SCALAR_ID",
    "DGUID",
    "UOM",
    "UOM_ID",
]
STATSCAN_TYPES = {
    "Age group": "category",
    "Sex": "category",
    "UOM": "category",
    "UOM_ID": "category",
    "GEO": "category",
    "SCALAR_FACTOR": "category",
    "SCALAR_ID": "category",
    "STATUS": "category",
    "SYMBOL": "category",
}


def read_statscan_csv(statcan_fn: str):
    return pd.read_csv(statcan_fn, dtype=STATSCAN_TYPES, low_memory=False)


def to_wide_format(statscan_data: pd.DataFrame, pivot_column):
    """
    Converts statscan data to wide format
    :param statscan_data:
    :return: a dataframe with the statscan data converted to wide format
    """
    base = statscan_data.copy()
    group_cols = [
        col
        for col in base.columns.tolist()
        if col not in CONTROL_COLS + [pivot_column, "VALUE"]
    ]
    # Assign a group number
    base["group"] = base.groupby(group_cols).ngroup()

    # Pivot on the group, turning the element into columns
    values = base.pivot_table(
        index="group",
        columns=pivot_column,
        values="VALUE",
        aggfunc=np.max,
        dropna=False,
    )
    # Drop Element and VALUE columns and drop duplicates
    base = base.drop(columns=[pivot_column, "VALUE"]).drop_duplicates(subset=group_cols)
    # Now merge with values
    return base.merge(values, on="group").drop(columns="group")


_STATSCAN_DATASET_RE = re.compile("(\d+)(\-(eng|fra))?\.(\w+)+")


class StatscanUrl:
    def __init__(
        self,
        baseurl: str,
        file: str,
        resourceid: str,
        extension: str,
        data: str,
        metadata: str,
        language: str = None,
    ):
        self.baseurl = baseurl
        self.file = file
        self.resourceid = resourceid
        self.language = language
        self.partitions = [language]
        self.extension = extension
        self.data = data
        self.metadata = metadata

    @classmethod
    def parse_from_filename(cls, url: str):
        filename = os.path.basename(url)
        baseurl = url[: url.index(filename)]
        match = _STATSCAN_DATASET_RE.match(filename)
        if match:
            file = match.group(0)
            resourceid = match.group(1)
            language = match.group(3)
            extension = match.group(4)
            data = f"{match.group(1)}.csv"
            metadata = f"{match.group(1)}_MetaData.csv"
            return StatscanUrl(
                baseurl=baseurl,
                file=file,
                resourceid=resourceid,
                extension=extension,
                data=data,
                metadata=metadata,
                language=language,
            )
        else:
            raise ValueError("Does not seem to be a valid statscan dataset url: " + url)

    def id(self):
        return f"{self.baseurl}{self.resourceid}"

    def __repr__(self):
        return f"StatscanUrl {self.__dict__}"


statscan_zipurl_re = re.compile(r".*[0-9]+(\-(en|fr)\w+?)?\.zip.*?")


class StatscanZip(object):
    def __init__(self, url: str, repo: Repo = None):
        assert statscan_zipurl_re.fullmatch(url)
        self.url: str = url
        self.url_info: StatscanUrl = StatscanUrl.parse_from_filename(url)
        self.repo: Repo = repo or Repo.at_user_home()

    def dimensions(self):
        return self.get_metadata().dimensions

    def primary_dimension(self):
        return self.get_metadata().pivot_column()

    def get_units_of_measure(self):
        return self.units_of_measure

    @classmethod
    def _apply_dtypes(cls, data: pd.DataFrame):
        for col in data:
            if col in ["REF_DATE"]:
                data[col] = pd.to_datetime(data[col]).dt.normalize()

    def _fetch_data(self):
        resource_id: str = self.url_info.resourceid
        data_file, metadata_file = self.repo.unzip(self.url, resource_id=resource_id)
        return data_file, metadata_file

    def transform_statscan_data(
        self,
        data: pd.DataFrame,
        wide=True,
        index_col: str = None,
        drop_control_cols=True,
    ):
        primary_dimension = self.primary_dimension()
        units_of_measure = (
            data[[primary_dimension, "UOM"]]
            .drop_duplicates()
            .set_index(primary_dimension)
            .sort_index()
        )
        setattr(self, "units_of_measure", units_of_measure)
        if wide:
            data = to_wide_format(data, pivot_column=self.primary_dimension())
        if index_col:
            data = data.set_index(index_col)

        if drop_control_cols:
            drop_cols = [col for col in CONTROL_COLS if col in data.columns]
            data = data.drop(columns=drop_cols)

        # Convert types
        if 'REF_DATE' in data:
            if not data['REF_DATE'].isnull().any():
                data['REF_DATE'] = pd.to_datetime(data['REF_DATE'])

        data = data.rename(columns={'REF_DATE': 'Date', 'GEO':'Geo'})
        return data

    def _set_metadata(self, metadata_file):
        meta_df: pd.DataFrame = pd.read_csv(metadata_file)
        metadata: StatscanMetadata = StatscanMetadata(meta_df)
        setattr(self, "metadata", metadata)

    def get_metadata(self):
        if not hasattr(self, "metadata"):
            data_file, metadata_file = self._fetch_data()
            self._set_metadata(metadata_file)
        return self.metadata

    def get_data(
        self,
        wide=True,
        index_col: str = None,
        drop_control_cols=True
    ):
        """
        Get the data from this zipfile
        :param wide: whether to make this a wide dataset
        :param index_col: the column to use as the index
        :param drop_control_cols: whether to drop the control columns
        :return: a Dataframe containing the data
        """
        if not hasattr(self, "data"):
            data_file, metadata_file = self._fetch_data()
            self._set_metadata(metadata_file)
            data_raw = read_statscan_csv(data_file)
            data = self.transform_statscan_data(
                data_raw,
                wide=wide,
                index_col=index_col,
                drop_control_cols=drop_control_cols,
            )
            setattr(self, "data", data)
        return self.data

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.url}>"


class StatscanMetadata(object):
    def __init__(self, meta_df: pd.DataFrame):
        self.cube_info = meta_df.head(1).set_index("Cube Title").T

        note_row = meta_df[meta_df["Cube Title"] == "Note ID"].index.item()
        correction_row = meta_df[meta_df["Cube Title"] == "Correction ID"].index.item()

        self.note = meta_df.iloc[note_row + 1 : correction_row, 0:2]
        self.note.columns = ["Note ID", "Note"]
        self.note = self.note.set_index("Note ID")

        dimension2_row = (
            meta_df[meta_df["Cube Title"] == "Dimension ID"].tail(1).index.item()
        )
        self.dimensions = meta_df.iloc[2:dimension2_row, 0:4]
        self.dimensions.columns = [
            "Dimension ID",
            "Dimension name",
            "Dimension Notes",
            "Dimension Definitions",
        ]
        self.dimensions = self.dimensions.set_index("Dimension ID")

        self.dimensions["Dimension Notes"] = self.dimensions["Dimension Notes"].map(
            self.note["Note"]
        )

        symbol_row = meta_df[meta_df["Cube Title"] == "Symbol Legend"].index.item()
        self.dimension_details = meta_df.iloc[dimension2_row + 1 : symbol_row, 0:8]
        self.dimension_details.columns = [
            "Dimension ID",
            "Member Name",
            "Classification Code",
            "Member ID",
            "Parent Member ID",
            "Terminated",
            "Member Notes",
            "Member Definitions",
        ]
        self.dimension_details = self.dimension_details.set_index("Dimension ID")

        survey_row = meta_df[meta_df["Cube Title"] == "Survey Code"].index.item()
        self.survey = meta_df.iloc[survey_row + 1 : survey_row + 2, 0:2]
        self.survey.columns = ["Survey Code", "Survey Name"]
        self.survey = self.survey.set_index("Survey Code")
        self.name = self.survey["Survey Name"].item()

        subject_row = meta_df[meta_df["Cube Title"] == "Subject Code"].index.item()
        self.subject = meta_df.iloc[subject_row + 1 : subject_row + 2, 0:2]
        self.subject.columns = ["Subject Code", "Subject Name"]
        self.subject = self.subject.set_index("Subject Code")

    def pivot_column(self):
        return self.dimensions.tail(1)["Dimension name"].item()

    def __repr__(self):
        return f"<{self.name}>"

    def _repr_html_(self):
        """
        This is for Jupyter notebooks to automatically display the metadata
        :return:
        """
        _html = f"<h2>{self.name}</h2>"
        _html += self.cube_info._repr_html_()
        _html += "<h3>Dimensions</h3>"
        _html += self.dimensions._repr_html_()
        _html += "<h3>Notes</h3>"
        _html += self.note._repr_html_()
        return _html
