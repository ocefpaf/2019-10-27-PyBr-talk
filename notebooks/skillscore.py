from itertools import cycle

import folium
import pandas as pd
from bokeh.embed import file_html
from bokeh.models import HoverTool, Legend
from bokeh.palettes import Category20
from bokeh.plotting import figure
from bokeh.resources import CDN
from folium import IFrame
from netCDF4 import Dataset
from owslib import fes

from ioos_tools.ioos import fes_date_filter, get_coordinates, stations_keys

# Plot defaults.
colors = Category20[20]
colorcycler = cycle(colors)
tools = "pan,box_zoom,reset"
width, height = 750, 250

# Some known models names. Unknonwn models will use the title metadata or the URL.
titles = {
    "coawst_4_use_best": "COAWST_4",
    "global": "HYCOM",
    "NECOFS_GOM3_FORECAST": "NECOFS_GOM3",
    "NECOFS_FVCOM_OCEAN_MASSBAY_FORECAST": "NECOFS_MassBay",
    "OBS_DATA": "Observations",
}


def make_plot(df, station, skill_score, mean_bias):
    p = figure(
        toolbar_location="above",
        x_axis_type="datetime",
        width=width,
        height=height,
        tools=tools,
        title=str(station),
    )
    leg = []
    for column, series in df.iteritems():
        series.dropna(inplace=True)
        if not series.empty:
            if "OBS_DATA" not in column:
                bias = mean_bias[str(station)][column]
                skill = skill_score[str(station)][column]
                line_color = next(colorcycler)
                kw = {"alpha": 0.65, "line_color": line_color}
            else:
                skill = bias = "NA"
                kw = {"alpha": 1, "color": "crimson"}
            line = p.line(
                x=series.index,
                y=series.values,
                line_width=5,
                line_cap="round",
                line_join="round",
                **kw
            )
            leg.append(("{}".format(titles.get(column, column)), [line]))
            p.add_tools(
                HoverTool(
                    tooltips=[
                        ("Name", "{}".format(titles.get(column, column))),
                        ("Bias", bias),
                        ("Skill", skill),
                    ],
                    renderers=[line],
                )
            )
    legend = Legend(items=leg, location=(0, 60))
    legend.click_policy = "mute"
    p.add_layout(legend, "right")
    p.yaxis[0].axis_label = "Wave Height (m)"
    p.xaxis[0].axis_label = "Date/time"
    return p


def make_marker(p, station, config):
    lons = stations_keys(config, key="lon")
    lats = stations_keys(config, key="lat")

    lon, lat = lons[station], lats[station]
    html = file_html(p, CDN, station)
    iframe = IFrame(html, width=width + 40, height=height + 80)

    popup = folium.Popup(iframe, max_width=2650)
    icon = folium.Icon(color="green", icon="stats")
    marker = folium.Marker(location=[lat, lon], popup=popup, icon=icon)
    return marker


def rename_cols(df, config):
    cols = stations_keys(config, key="station_name")
    return df.rename(columns=cols)


def check_standard_name(url, standard_names):
    def standard_name(v):
        return v in standard_names

    with Dataset(url) as nc:
        variables = nc.get_variables_by_attributes(standard_name=standard_name)
    if variables:
        return True
    else:
        return False


def make_map(bbox, **kw):
    line = kw.pop("line", True)
    layers = kw.pop("layers", True)
    zoom_start = kw.pop("zoom_start", 5)

    lon = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    m = folium.Map(
        width="100%", height="100%", location=[lat, lon], zoom_start=zoom_start
    )

    if layers:
        url = "http://geoport-dev.whoi.edu/thredds/wms/coawst_4/use/fmrc/coawst_4_use_best.ncd"
        w = folium.WmsTileLayer(
            url,
            name="COAWST Wave Height",
            fmt="image/png",
            layers="Hwave",
            style="boxfill/rainbow",
            COLORSCALERANGE="0,5",
            overlay=True,
            transparent=True,
        )

        w.add_to(m)

    if line:
        p = folium.PolyLine(
            get_coordinates(bbox),
            color="#FF0000",
            weight=2,
            opacity=0.9,
            latlon=True,
        )
        p.add_to(m)
    return m


def get_df(dfs, station):
    ret = {}
    for k, v in dfs.items():
        ret.update({k: v[station]})
    return pd.DataFrame.from_dict(ret)


def make_filter(config,):
    kw = {
        "wildCard": "*",
        "escapeChar": "\\",
        "singleChar": "?",
        "propertyname": "apiso:Subject",
    }

    if len(config["cf_names"]) > 1:
        or_filt = fes.Or(
            [
                fes.PropertyIsLike(literal=("*%s*" % val), **kw)
                for val in config["cf_names"]
            ]
        )
    else:
        or_filt = fes.PropertyIsLike(
            literal=("*%s*" % config["cf_names"][0]), **kw
        )

    kw.update({"propertyname": "apiso:AnyText"})
    not_filt = fes.Not([fes.PropertyIsLike(literal="*cdip*", **kw)])

    begin, end = fes_date_filter(
        config["date"]["start"], config["date"]["stop"]
    )
    bbox_crs = fes.BBox(config["region"]["bbox"], crs=config["region"]["crs"])
    filter_list = [fes.And([bbox_crs, begin, end, or_filt, not_filt])]
    return filter_list
