"""All navigable screens."""

from .assurance import AssuranceScreen
from .budget import BudgetScreen
from .career import CareerScreen
from .crisis import CrisisScreen
from .dashboard import DashboardScreen
from .final import FinalScreen
from .finance import FinanceScreen
from .kri import KRIScreen
from .mission import MissionScreen
from .missions import MissionsScreen
from .organisation import OrganisationScreen
from .portfolio import PortfolioScreen
from .profile import ProfileScreen, SkillTreeScreen
from .register import RegisterScreen
from .reports import ReportsScreen
from .review import ReviewScreen
from .settings import SavesScreen, SettingsScreen
from .stakeholders import StakeholdersScreen
from .startup import StartupScreen
from .training import TrainingScreen
from .workbench import WorkbenchScreen

ALL_SCREENS = [StartupScreen, DashboardScreen, CareerScreen, ProfileScreen, SkillTreeScreen, MissionsScreen,
               MissionScreen, RegisterScreen, WorkbenchScreen, AssuranceScreen, FinanceScreen, KRIScreen,
               CrisisScreen, StakeholdersScreen, BudgetScreen, ReportsScreen, ReviewScreen, TrainingScreen,
               PortfolioScreen, OrganisationScreen, SettingsScreen, SavesScreen, FinalScreen]
