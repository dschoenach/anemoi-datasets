# (C) Copyright 2024 Anemoi contributors.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
#
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.


import logging
from collections import defaultdict
from typing import Any
from typing import Generator
from typing import Tuple

import numpy as np
from anemoi.transform.fields import new_field_with_valid_datetime
from anemoi.transform.fields import new_fieldlist_from_list
from anemoi.utils.dates import as_datetime
from anemoi.utils.dates import frequency_to_timedelta

from .action import Action
from .action import action_factory
from .join import JoinResult
from .result import Result
from .trace import trace_select

LOG = logging.getLogger(__name__)


class DateMapper:

    @staticmethod
    def from_mode(mode: str, source: Any, config: dict) -> "DateMapper":

        MODES = dict(
            closest=DateMapperClosest,
            climatology=DateMapperClimatology,
            constant=DateMapperConstant,
        )

        if mode not in MODES:
            raise ValueError(f"Invalid mode for DateMapper: {mode}")

        return MODES[mode](source, **config)


class DateMapperClosest(DateMapper):
    def __init__(self, source: Any, frequency: str = "1h", maximum: str = "30d", skip_all_nans: bool = False) -> None:
        self.source = source
        self.maximum = frequency_to_timedelta(maximum)
        self.frequency = frequency_to_timedelta(frequency)
        self.skip_all_nans = skip_all_nans
        self.tried = set()
        self.found = set()

    def transform(self, group_of_dates: Any) -> Generator[Tuple[Any, Any], None, None]:
        from anemoi.datasets.dates.groups import GroupOfDates

        asked_dates = list(group_of_dates)
        if not asked_dates:
            return

        to_try = set()
        for date in asked_dates:
            start = date
            while start >= date - self.maximum:
                to_try.add(start)
                start -= self.frequency

            end = date
            while end <= date + self.maximum:
                to_try.add(end)
                end += self.frequency

        to_try = sorted(to_try - self.tried)
        info = {k: "no-data" for k in to_try}

        if not to_try:
            LOG.warning(f"No new dates to try for {group_of_dates} in {self.source}")

        if to_try:
            result = self.source.select(
                GroupOfDates(
                    sorted(to_try),
                    group_of_dates.provider,
                    partial_ok=True,
                )
            )

            cnt = 0
            for f in result.datasource:
                cnt += 1
                date = as_datetime(f.metadata("valid_datetime"))

                if self.skip_all_nans:
                    if np.isnan(f.to_numpy()).all():
                        LOG.warning(f"Skipping {date} because all values are NaN")
                        info[date] = "all-nans"
                        continue

                info[date] = "ok"
                self.found.add(date)

            if cnt == 0:
                raise ValueError(f"No data found for {group_of_dates} in {self.source}")

            self.tried.update(to_try)

        if not self.found:
            for k, v in info.items():
                LOG.warning(f"{k}: {v}")

            raise ValueError(f"No matching data found for {asked_dates} in {self.source}")

        new_dates = defaultdict(list)

        for date in asked_dates:
            best = None
            for found_date in sorted(self.found):
                delta = abs(date - found_date)
                if best is None or delta <= best[0]:
                    best = delta, found_date
            new_dates[best[1]].append(date)

        for date, dates in new_dates.items():
            yield (
                GroupOfDates([date], group_of_dates.provider),
                GroupOfDates(dates, group_of_dates.provider),
            )


class DateMapperClimatology(DateMapper):
    def __init__(self, source: Any, year: int, day: int, hour: int = None) -> None:
        self.year = year
        self.day = day
        self.hour = hour

    def transform(self, group_of_dates: Any) -> Generator[Tuple[Any, Any], None, None]:
        from anemoi.datasets.dates.groups import GroupOfDates

        dates = list(group_of_dates)
        if not dates:
            return

        new_dates = defaultdict(list)
        for date in dates:
            new_date = date.replace(year=self.year, day=self.day)
            if self.hour is not None:
                new_date = new_date.replace(hour=self.hour, minute=0, second=0)
            new_dates[new_date].append(date)

        for date, dates in new_dates.items():
            yield (
                GroupOfDates([date], group_of_dates.provider),
                GroupOfDates(dates, group_of_dates.provider),
            )


class DateMapperConstant(DateMapper):
    def __init__(self, source: Any, date: Any = None) -> None:
        self.source = source
        self.date = date

    def transform(self, group_of_dates: Any) -> Generator[Tuple[Any, Any], None, None]:
        from anemoi.datasets.dates.groups import GroupOfDates

        if self.date is None:
            yield (
                GroupOfDates([], group_of_dates.provider),
                group_of_dates,
            )
            return

        yield (
            GroupOfDates([self.date], group_of_dates.provider),
            group_of_dates,
        )


class DateMapperResult(Result):
    def __init__(
        self,
        context: Any,
        action_path: list,
        group_of_dates: Any,
        source_result: Any,
        mapper: DateMapper,
        original_group_of_dates: Any,
    ) -> None:
        super().__init__(context, action_path, group_of_dates)

        self.source_results = source_result
        self.mapper = mapper
        self.original_group_of_dates = original_group_of_dates

    @property
    def datasource(self) -> Any:
        result = []

        for field in self.source_results.datasource:
            for date in self.original_group_of_dates:
                result.append(new_field_with_valid_datetime(field, date))

        if not result:
            raise ValueError("repeated_dates: no input data found")

        return new_fieldlist_from_list(result)


class RepeatedDatesAction(Action):
    def __init__(self, context: Any, action_path: list, source: Any, mode: str, **kwargs: Any) -> None:
        super().__init__(context, action_path, source, mode, **kwargs)

        self.source = action_factory(source, context, action_path + ["source"])
        self.mapper = DateMapper.from_mode(mode, self.source, kwargs)

    @trace_select
    def select(self, group_of_dates: Any) -> JoinResult:
        results = []
        for one_date_group, many_dates_group in self.mapper.transform(group_of_dates):
            results.append(
                DateMapperResult(
                    self.context,
                    self.action_path,
                    one_date_group,
                    self.source.select(one_date_group),
                    self.mapper,
                    many_dates_group,
                )
            )

        return JoinResult(self.context, self.action_path, group_of_dates, results)

    def __repr__(self) -> str:
        return f"MultiDateMatchAction({self.source}, {self.mapper})"
