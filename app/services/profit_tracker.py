"""
Profit Tracker service

Calculates historical profits, trends, and future projections
based on loot income and material costs.
"""
from datetime import datetime, timedelta, date
from typing import Optional
import statistics

from app import db
from app.models.voyage_loot import VoyageLoot
from app.models.app_settings import AppSettings
from sqlalchemy import func

from app.utils.logging import get_logger

logger = get_logger('ProfitTracker')


class ProfitTracker:
    """
    Tracks and projects submarine fleet profits.
    """

    # Average material consumption per voyage (estimates)
    # These are reasonable defaults based on typical voyage configurations
    DEFAULT_CERULEUM_PER_VOYAGE = 4.0  # tanks
    DEFAULT_KITS_PER_VOYAGE = 0.15  # repair kits (partial, since not every voyage needs repair)

    _instance = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

    def get_material_costs(self) -> dict:
        """Get current material cost configuration."""
        return AppSettings.get_material_costs()

    def get_consumption_estimates(self) -> dict:
        """
        Get estimated material consumption per voyage.

        Returns dict with ceruleum_per_voyage and kits_per_voyage
        """
        # Try to calculate from current fleet data
        try:
            from app.services import get_fleet_manager
            fleet = get_fleet_manager()
            data = fleet.get_dashboard_data()

            total_ceruleum_per_day = data['supply_forecast']['ceruleum_per_day']
            total_kits_per_day = data['supply_forecast']['kits_per_day']
            total_subs = data['summary']['total_subs']

            if total_subs > 0:
                # Estimate ~2 voyages per sub per day on average
                voyages_per_day_estimate = total_subs * 2
                ceruleum_per_voyage = total_ceruleum_per_day / voyages_per_day_estimate if voyages_per_day_estimate > 0 else self.DEFAULT_CERULEUM_PER_VOYAGE
                kits_per_voyage = total_kits_per_day / voyages_per_day_estimate if voyages_per_day_estimate > 0 else self.DEFAULT_KITS_PER_VOYAGE
            else:
                ceruleum_per_voyage = self.DEFAULT_CERULEUM_PER_VOYAGE
                kits_per_voyage = self.DEFAULT_KITS_PER_VOYAGE

            return {
                'ceruleum_per_voyage': round(ceruleum_per_voyage, 2),
                'kits_per_voyage': round(kits_per_voyage, 3),
                'source': 'calculated'
            }
        except Exception as e:
            logger.info(f"Using default consumption estimates: {e}")
            return {
                'ceruleum_per_voyage': self.DEFAULT_CERULEUM_PER_VOYAGE,
                'kits_per_voyage': self.DEFAULT_KITS_PER_VOYAGE,
                'source': 'default'
            }

    def calculate_daily_cost(self, voyage_count: int) -> float:
        """
        Calculate estimated material cost for a given number of voyages.

        Args:
            voyage_count: Number of voyages

        Returns:
            Estimated gil cost for materials
        """
        costs = self.get_material_costs()
        consumption = self.get_consumption_estimates()

        ceruleum_cost = voyage_count * consumption['ceruleum_per_voyage'] * costs['ceruleum_price_per_unit']
        kit_cost = voyage_count * consumption['kits_per_voyage'] * costs['repair_kit_price_per_unit']

        return ceruleum_cost + kit_cost

    def get_daily_profits(self, days: int = 30, tz_offset_minutes: int = 0,
                          excluded_fc_ids=None, allowed_worlds=None) -> list[dict]:
        """
        Get daily profit data (income - costs).

        Args:
            days: Number of days to look back (0 = all)
            tz_offset_minutes: Client timezone offset in minutes (e.g., -480 for UTC+8, 480 for UTC-8)
            excluded_fc_ids: Set of FC IDs to exclude (from tag filters)
            allowed_worlds: Set of world names to include (from region filters), or None for all

        Returns:
            List of daily profit records with date, income, cost, profit
        """
        # Get hidden FC IDs to exclude from profit calculations
        try:
            from app.models.fc_config import get_hidden_fc_ids
            hidden_fc_ids = get_hidden_fc_ids()
        except Exception:
            hidden_fc_ids = set()

        # Merge filter-excluded FCs with hidden FCs
        all_excluded = hidden_fc_ids | (excluded_fc_ids or set())

        # Convert timezone offset to hours for SQLite datetime modifier
        # JavaScript's getTimezoneOffset() returns positive for west of UTC, negative for east
        # We need to subtract the offset to convert UTC to local time
        tz_offset_hours = -tz_offset_minutes / 60
        tz_modifier = f'{tz_offset_hours:+.1f} hours'

        # Query daily loot totals with timezone adjustment
        # Use datetime() with modifier to convert UTC to local time before extracting date
        local_datetime = func.datetime(VoyageLoot.captured_at, tz_modifier)
        local_date = func.date(local_datetime)

        daily_query = db.session.query(
            local_date.label('date'),
            func.count(VoyageLoot.id).label('voyages'),
            func.sum(VoyageLoot.total_gil_value).label('gross_income')
        )

        if days > 0:
            cutoff = datetime.utcnow() - timedelta(days=days)
            daily_query = daily_query.filter(VoyageLoot.captured_at >= cutoff)

        # Region filtering: resolve allowed_worlds to FC IDs since VoyageLoot has no world column
        if allowed_worlds is not None:
            try:
                from app.services import get_fleet_manager
                from app.services.submarine_data import get_world_region
                fleet = get_fleet_manager()
                accounts = fleet.get_data(force_refresh=False)
                # Find FC IDs whose world is NOT in allowed_worlds
                region_excluded_fc_ids = set()
                for account in accounts:
                    for char in account.characters:
                        if char.world not in allowed_worlds and char.fc_id:
                            region_excluded_fc_ids.add(str(char.fc_id))
                all_excluded = all_excluded | region_excluded_fc_ids
            except Exception:
                pass

        # Exclude hidden + filter-excluded FCs
        if all_excluded:
            daily_query = daily_query.filter(~VoyageLoot.fc_id.in_(all_excluded))

        daily_data = daily_query.group_by(
            local_date
        ).order_by(
            local_date
        ).all()

        results = []
        for row in daily_data:
            voyage_count = row.voyages
            gross_income = row.gross_income or 0
            material_cost = self.calculate_daily_cost(voyage_count)
            net_profit = gross_income - material_cost

            results.append({
                'date': str(row.date),
                'voyages': voyage_count,
                'gross_income': gross_income,
                'material_cost': round(material_cost, 0),
                'net_profit': round(net_profit, 0)
            })

        return results

    def calculate_trend_line(self, daily_profits: list[dict]) -> dict:
        """
        Calculate linear regression trend line from daily profit data.

        Args:
            daily_profits: List of daily profit records

        Returns:
            Dict with slope, intercept, and trend data points
        """
        if len(daily_profits) < 2:
            return {
                'slope': 0,
                'intercept': 0,
                'trend_points': [],
                'r_squared': 0,
                'daily_trend': 0
            }

        # Convert to x (days since start) and y (profit) values
        x_values = list(range(len(daily_profits)))
        y_values = [d['net_profit'] for d in daily_profits]

        # Calculate means
        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(y_values)

        # Calculate slope and intercept
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
        denominator = sum((x - x_mean) ** 2 for x in x_values)

        if denominator == 0:
            slope = 0
            intercept = y_mean
        else:
            slope = numerator / denominator
            intercept = y_mean - slope * x_mean

        # Calculate R-squared
        y_predicted = [slope * x + intercept for x in x_values]
        ss_res = sum((y - yp) ** 2 for y, yp in zip(y_values, y_predicted))
        ss_tot = sum((y - y_mean) ** 2 for y in y_values)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

        # Generate trend line points
        trend_points = []
        for i, day_data in enumerate(daily_profits):
            trend_points.append({
                'date': day_data['date'],
                'value': round(slope * i + intercept, 0)
            })

        return {
            'slope': round(slope, 2),
            'intercept': round(intercept, 0),
            'trend_points': trend_points,
            'r_squared': round(r_squared, 3),
            'daily_trend': round(slope, 0)  # How much profit changes per day
        }

    def project_future_profits(self, daily_profits: list[dict], trend: dict,
                                projection_days: int = 30) -> list[dict]:
        """
        Project future profits based on trend.

        Args:
            daily_profits: Historical daily profit data
            trend: Trend line data from calculate_trend_line
            projection_days: Number of days to project forward

        Returns:
            List of projected daily profit records
        """
        if not daily_profits:
            return []

        # Start from the day after the last data point
        last_date = datetime.strptime(daily_profits[-1]['date'], '%Y-%m-%d').date()
        last_x = len(daily_profits) - 1

        projections = []
        for i in range(1, projection_days + 1):
            future_date = last_date + timedelta(days=i)
            future_x = last_x + i
            projected_profit = trend['slope'] * future_x + trend['intercept']

            projections.append({
                'date': str(future_date),
                'projected_profit': round(projected_profit, 0)
            })

        return projections

    def get_profit_summary(self, days: int = 30, projection_days: int = 30, tz_offset_minutes: int = 0,
                           excluded_fc_ids=None, allowed_worlds=None) -> dict:
        """
        Get complete profit analysis with history, trend, and projections.

        Args:
            days: Days of historical data (0 = all)
            projection_days: Days to project forward
            tz_offset_minutes: Client timezone offset in minutes
            excluded_fc_ids: Set of FC IDs to exclude (from tag filters)
            allowed_worlds: Set of world names to include (from region filters), or None for all

        Returns:
            Complete profit analysis dict
        """
        daily_profits = self.get_daily_profits(days=days, tz_offset_minutes=tz_offset_minutes,
                                               excluded_fc_ids=excluded_fc_ids, allowed_worlds=allowed_worlds)
        trend = self.calculate_trend_line(daily_profits)
        projections = self.project_future_profits(daily_profits, trend, projection_days)

        # Calculate summary statistics
        if daily_profits:
            total_gross = sum(d['gross_income'] for d in daily_profits)
            total_costs = sum(d['material_cost'] for d in daily_profits)
            total_profit = sum(d['net_profit'] for d in daily_profits)
            total_voyages = sum(d['voyages'] for d in daily_profits)
            num_days = len(daily_profits)

            avg_daily_profit = total_profit / num_days if num_days > 0 else 0
            avg_daily_income = total_gross / num_days if num_days > 0 else 0
            avg_daily_cost = total_costs / num_days if num_days > 0 else 0
            profit_margin = (total_profit / total_gross * 100) if total_gross > 0 else 0

            # Project totals
            projected_30d_profit = avg_daily_profit * 30
            projected_monthly_profit = avg_daily_profit * 30
        else:
            total_gross = total_costs = total_profit = total_voyages = 0
            avg_daily_profit = avg_daily_income = avg_daily_cost = 0
            profit_margin = 0
            projected_30d_profit = projected_monthly_profit = 0
            num_days = 0

        # Get current material costs for display
        material_costs = self.get_material_costs()
        consumption = self.get_consumption_estimates()

        return {
            'period_days': days if days > 0 else 'all',
            'actual_days': num_days,
            'daily_profits': daily_profits,
            'trend': trend,
            'projections': projections,
            'summary': {
                'total_gross_income': round(total_gross, 0),
                'total_material_cost': round(total_costs, 0),
                'total_net_profit': round(total_profit, 0),
                'total_voyages': total_voyages,
                'avg_daily_profit': round(avg_daily_profit, 0),
                'avg_daily_income': round(avg_daily_income, 0),
                'avg_daily_cost': round(avg_daily_cost, 0),
                'profit_margin_pct': round(profit_margin, 1),
                'projected_30d_profit': round(projected_30d_profit, 0),
                'trend_direction': 'up' if trend['slope'] > 0 else 'down' if trend['slope'] < 0 else 'flat',
                'trend_daily_change': trend['daily_trend'],
                'r_squared': trend['r_squared']
            },
            'costs': {
                'ceruleum_price_per_stack': material_costs['ceruleum_price_per_stack'],
                'repair_kit_price_per_stack': material_costs['repair_kit_price_per_stack'],
                'ceruleum_per_voyage': consumption['ceruleum_per_voyage'],
                'kits_per_voyage': consumption['kits_per_voyage']
            }
        }


# Singleton instance
profit_tracker = ProfitTracker()
