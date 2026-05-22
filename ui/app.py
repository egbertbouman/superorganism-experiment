from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QStackedWidget

from bitcoin.rpc_errors import BitcoinRpcError
from config import UI_REFRESH_DELAY
from democracy.democracy_service import DemocracyService
from democracy.funding.models import FundingCampaign
from democracy.funding.service import FundingService
from democracy.funding.service import FundingStatus
from democracy.models.person import Person
from democracy.models.solution import Solution
from ui.models.issue_draft import IssueDraft
from ui.models.pledge_draft import PledgeDraft
from ui.models.signed_pledge_draft import SignedPledgeDraft
from ui.models.solution_draft import SolutionDraft
from ui.widgets.fleet_widget import FleetWidget
from ui.widgets.issue_details import IssueDetailWidget
from ui.widgets.issue_overview import IssuesOverviewWidget
from ui.widgets.ltr_community_widget import LTRCommunityWidget
from ui.widgets.overlays.create_issue_overlay import CreateIssueOverlay
from ui.widgets.overlays.create_pledge_overlay import CreatePledgeOverlay, \
    PledgeOverlayContext, PendingPledgeRequest
from ui.widgets.overlays.create_solution_overlay import CreateSolutionOverlay
from ui.widgets.sidebar import SidebarWidget
from ui.widgets.solution_details import (
    SolutionDetailWidget,
    SolutionFundingPanelState,
    SolutionSidePanelStatus,
)
from ui.widgets.torrents_widget import TorrentsWidget

from crowdsourced_learn_to_rank.ltr_community_thread import LTRCommunityThread

if TYPE_CHECKING:
    from healthchecker.health_thread import TorrentHealthThread

logger = logging.getLogger(f"superorganism.{__name__}")


class Application(QMainWindow):
    """
    Main application class for the Democracy UI.
    Manages the main window and coordinates between different widgets.
    1. Create Issue Widget (left top)
    2. Issue Detail Widget (right top)
    3. Issue List Widget (bottom, spans full width)
    4. Session user management
    5. Event handling for creating issues, selecting issues, and voting.
    6. Data loading and refreshing.

    Args:
        user (Person): Current session user.
        democracy_service (DemocracyService): Application-facing democracy service.
    """

    def __init__(
        self,
        user: Person,
        democracy_service: DemocracyService,
        funding_service: FundingService,
        health_thread: TorrentHealthThread,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.user = user
        self.democracy_service = democracy_service
        self.funding_service = funding_service

        self._health_thread = health_thread

        self.setWindowTitle("Democracy")
        self.resize(1360, 820)

        # Coalesced refresh state
        self._refresh_pending = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)

        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)

        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = SidebarWidget()

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("contentStackHost")

        self.issues_page = IssuesOverviewWidget()

        self.issues_page.create_clicked.connect(self._open_create_overlay)
        self.issues_page.search_changed.connect(self._on_search_changed)
        self.issues_page.filter_changed.connect(self._on_filter_changed)
        self.issues_page.issue_selected.connect(self._on_select)
        self.issues_page.issue_activated.connect(self._open_issue_details)

        self.issue_detail_page = IssueDetailWidget()

        self.issue_detail_page.back_clicked.connect(self._show_issues_page)
        self.issue_detail_page.approved.connect(self._on_vote)
        self.issue_detail_page.solution_voted.connect(self._on_solution_vote)
        self.issue_detail_page.solution_details_requested.connect(
            self._on_solution_details
        )
        self.issue_detail_page.open_create_solution.connect(
            self._open_create_solution_overlay
        )

        self._solution_target_issue_id: Optional[UUID] = None

        self.solution_detail_page = SolutionDetailWidget()
        self.solution_detail_page.back_clicked.connect(
            self._show_issue_detail_page_for_current_issue
        )
        self.solution_detail_page.voted.connect(self._on_vote_solution_directly)
        self.solution_detail_page.code_verification_clicked.connect(
            self._on_code_verification_clicked
        )
        self.solution_detail_page.create_pledge_requested.connect(
            self._open_create_pledge_overlay
        )

        self.torrents_page = TorrentsWidget()
        self.fleet_page = FleetWidget()

        self.experiment_page = LTRCommunityWidget()
        self.experiment_page.run_requested.connect(self._on_experiment_run_requested)
        self.experiment_page.stop_requested.connect(self._on_experiment_stop_requested)
        self._ltr_thread: Optional[LTRCommunityThread] = None

        self.content_stack.addWidget(self.torrents_page)
        self.content_stack.addWidget(self.fleet_page)
        self.content_stack.addWidget(self.issues_page)
        self.content_stack.addWidget(self.issue_detail_page)
        self.content_stack.addWidget(self.solution_detail_page)
        self.content_stack.addWidget(self.experiment_page)

        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(self.content_stack, 1)

        self.content_stack.setCurrentWidget(self.issues_page)

        self.sidebar.torrents_clicked.connect(self._show_torrents_page)
        self.sidebar.fleet_clicked.connect(self._show_fleet_page)
        self.sidebar.issues_clicked.connect(self._show_issues_page)
        self.sidebar.my_issues_clicked.connect(lambda: logger.info("My Issues clicked"))
        self.sidebar.voting_history_clicked.connect(
            lambda: logger.info("Voting History clicked")
        )
        self.sidebar.experiment_clicked.connect(self._show_experiment_page)
        self.sidebar.settings_clicked.connect(lambda: logger.info("Settings clicked"))
        self.sidebar.create_clicked.connect(self._open_create_overlay)

        health_thread.dataChanged.connect(
            self._on_health_data_changed, type=Qt.ConnectionType.QueuedConnection
        )

        # Populate torrent table immediately with all known peers (unchecked show "-")
        self.torrents_page.load(health_thread.get_torrent_data())

        self.create_issue_overlay = CreateIssueOverlay(root)
        self.create_issue_overlay.created.connect(self._on_create_issue)
        self.create_issue_overlay.hide()

        self.create_solution_overlay = CreateSolutionOverlay(root)
        self.create_solution_overlay.created.connect(self._on_create_solution)
        self.create_solution_overlay.hide()

        self.create_pledge_overlay = CreatePledgeOverlay(root)
        self.create_pledge_overlay.pledge_request_requested.connect(
            self._on_create_pledge_request
        )
        self.create_pledge_overlay.signed_pledge_submitted.connect(
            self._on_submit_signed_pledge
        )
        self.create_pledge_overlay.closed.connect(self._on_create_pledge_overlay_closed)
        self.create_pledge_overlay.hide()

        self._pledge_overlay_context: Optional[PledgeOverlayContext] = None
        self._pending_pledge_request: Optional[PendingPledgeRequest] = None

        # Initial load
        self.refresh()

        self._apply_styles()

    def _apply_styles(self) -> None:
        with open("ui/styles/main.qss", "r") as f:
            self.setStyleSheet(f.read())

    # -----------------------------
    # Refresh API
    # -----------------------------
    def refresh(self) -> None:
        """
        Immediate refresh (useful for local UI actions).
        """
        self.issues_page.load(self.democracy_service.get_all_issues_with_votes())

        current_id = self.issue_detail_page.current_issue_id
        if current_id:
            issue = self.democracy_service.get_issue_with_votes(current_id)
            if issue:
                solutions = self.democracy_service.get_solutions_for_issue_with_votes(
                    current_id
                )
                self.issue_detail_page.show_issue(issue, solutions)

        current_solution_id = self.solution_detail_page.current_solution_id
        if current_solution_id:
            solution = self.democracy_service.get_solution_with_votes(current_solution_id)
            if solution:
                self.solution_detail_page.show_solution(
                    solution,
                    self._build_solution_funding_state(current_solution_id),
                )

    def schedule_refresh(self) -> None:
        """
        Coalesced refresh:
        - First call schedules a refresh in delay_ms.
        - Further calls before it fires do nothing.
        """
        if self._refresh_pending:
            return

        self._refresh_pending = True
        self._refresh_timer.start(UI_REFRESH_DELAY)

    def _do_refresh(self) -> None:
        self._refresh_pending = False
        self.refresh()

    def _open_create_overlay(self) -> None:
        self.create_issue_overlay.open_overlay()

    def _on_search_changed(self, text: str) -> None:
        self.issues_page.apply_search_filter(text)

    def _on_filter_changed(self, value: str) -> None:
        self.issues_page.apply_status_filter(value)

    # -----------------------------
    # Handlers
    # -----------------------------
    def _on_create_issue(self, draft: IssueDraft):
        """
        Handles creation of a new issue. Sets the creator to the current user and adds it to the store.
        Refreshes the issue list afterwards.

        :param draft: Issue to create.
        :return: None
        """
        errors = draft.validate()
        if errors:
            return

        self.democracy_service.create_issue(
            title=draft.title,
            description=draft.description,
            creator_id=self.user.id,
        )
        self.refresh()

    def _on_select(self, issue_id: UUID):
        """
        Handles selection of an issue from the list. Loads the issue details into the detail frame.

        :param issue_id: ID of the selected issue.
        :return: None
        """
        pass

    def _open_issue_details(self, issue_id: UUID) -> None:
        self._show_issue_detail_page(issue_id)

    def _on_vote(self, issue_id: UUID):
        """
        Handles voting on an issue. Checks if the user has already voted, and if not, records the vote.
        Refreshes the issue list afterwards.

        :param issue_id: ID of the selected issue.
        :return: None
        """
        vote = self.democracy_service.vote_for_issue(self.user.id, issue_id)
        if vote is None:
            return  # already voted

        self.refresh()

    def _on_solution_vote(self, _issue_id: UUID, solution_id: UUID) -> None:
        vote = self.democracy_service.vote_for_solution(self.user.id, solution_id)
        if vote is None:
            return

        self.refresh()

    def _on_solution_details(self, issue_id: UUID, solution_id: UUID) -> None:
        solution = self.democracy_service.get_solution_with_votes(solution_id)
        if not solution:
            return

        self._current_parent_issue_id = issue_id
        self.solution_detail_page.show_solution(
            solution,
            self._build_solution_funding_state(solution_id),
        )
        self.content_stack.setCurrentWidget(self.solution_detail_page)

    def _build_solution_funding_state(
        self,
        solution_id: UUID,
    ) -> SolutionFundingPanelState:
        campaign = self.funding_service.repository.get_campaign_for_solution(solution_id)
        if campaign is None or not campaign.is_active:
            return SolutionFundingPanelState(has_campaign=False)

        try:
            funding_status = self.funding_service.compute_funding_status(
                campaign_id=campaign.id,
                fee_buffer_sats=0,
            )
        except (BitcoinRpcError, ValueError):
            logger.exception(
                "Failed to compute funding status for solution %s and campaign %s.",
                solution_id,
                campaign.id,
            )
            return self._build_funding_state_without_live_status(campaign)

        return self._build_funding_state_from_status(campaign, funding_status)

    @staticmethod
    def _build_funding_state_without_live_status(
        campaign: FundingCampaign,
    ) -> SolutionFundingPanelState:
        return SolutionFundingPanelState(
            has_campaign=True,
            can_create_pledge=True,
            raised_sats=0,
            target_sats=campaign.asking_price_sats,
            valid_pledge_count=0,
            deadline_height=campaign.deadline_height,
            payout_address=campaign.developer_payout_address or "",
            status=SolutionSidePanelStatus.OPEN,
        )

    @staticmethod
    def _build_funding_state_from_status(
        campaign: FundingCampaign,
        funding_status: FundingStatus,
    ) -> SolutionFundingPanelState:
        if funding_status.is_fundable:
            status = SolutionSidePanelStatus.COMPLETED
        elif funding_status.is_expired:
            status = SolutionSidePanelStatus.EXPIRED
        else:
            status = SolutionSidePanelStatus.OPEN

        return SolutionFundingPanelState(
            has_campaign=True,
            can_create_pledge=not funding_status.is_expired,
            raised_sats=funding_status.valid_pledge_total_sats,
            target_sats=funding_status.required_total_sats,
            valid_pledge_count=funding_status.valid_pledge_count,
            deadline_height=campaign.deadline_height,
            payout_address=campaign.developer_payout_address or "",
            status=status,
        )

    def _open_create_pledge_overlay(self, solution_id: UUID) -> None:
        context = self._build_pledge_overlay_context(solution_id)
        if context is None:
            logger.warning(
                "Cannot open pledge overlay for solution %s because no active funding campaign exists.",
                solution_id,
            )
            return

        self._pledge_overlay_context = context
        self._pending_pledge_request = None
        self.create_pledge_overlay.open_overlay(context)

    def _build_pledge_overlay_context(
        self,
        solution_id: UUID,
    ) -> Optional[PledgeOverlayContext]:
        solution_with_votes = self.democracy_service.get_solution_with_votes(solution_id)
        if solution_with_votes is None:
            return None

        campaign = self.funding_service.repository.get_campaign_for_solution(solution_id)
        if campaign is None or not campaign.is_active:
            return None

        funding_state = self._build_solution_funding_state(solution_id)
        raised_sats = funding_state.raised_sats or 0
        target_sats = funding_state.target_sats or campaign.asking_price_sats

        return PledgeOverlayContext(
            campaign_id=campaign.id,
            solution_title=solution_with_votes.solution.title,
            asking_price_sats=target_sats,
            raised_sats=raised_sats,
            deadline_height=campaign.deadline_height,
            payout_address=campaign.developer_payout_address or "",
            status_text=(funding_state.status or SolutionSidePanelStatus.OPEN).value.upper(),
        )

    def _on_create_pledge_request(self, draft: PledgeDraft) -> None:
        if self._pledge_overlay_context is None:
            logger.warning("Ignoring pledge request because no pledge overlay context is active.")
            return

        errors = draft.validate()
        if errors:
            return

        try:
            pledge_request = self.funding_service.create_pledge_request(
                campaign_id=self._pledge_overlay_context.campaign_id,
                pledger_id=self.user.id,
                txid=draft.normalized_txid,
                vout=draft.normalized_vout,
            )
        except (BitcoinRpcError, ValueError) as exc:
            print(f"Failed to create pledge request: {exc}")
            logger.exception(
                "Failed to create pledge request for campaign %s.",
                self._pledge_overlay_context.campaign_id,
            )
            return

        self._pending_pledge_request = PendingPledgeRequest(
            txid=draft.normalized_txid,
            vout=draft.normalized_vout,
            pledge_request=pledge_request,
        )
        self.create_pledge_overlay.show_signing_step(self._pending_pledge_request)

    def _on_submit_signed_pledge(self, draft: SignedPledgeDraft) -> None:
        if self._pending_pledge_request is None:
            logger.warning("Ignoring signed pledge submission because no pending pledge request exists.")
            return

        errors = draft.validate()
        if errors:
            return

        try:
            pledge = self.funding_service.submit_signed_pledge(
                campaign_id=self._pending_pledge_request.pledge_request.campaign_id,
                pledger_id=self.user.id,
                txid=self._pending_pledge_request.txid,
                vout=self._pending_pledge_request.vout,
                signed_pledge_psbt=draft.normalized_signed_pledge_psbt,
            )
        except (BitcoinRpcError, ValueError) as exc:
            print(f"Failed to submit signed pledge: {exc}")
            logger.exception(
                "Failed to submit signed pledge for campaign %s.",
                self._pending_pledge_request.pledge_request.campaign_id,
            )
            return

        print(pledge)
        self.create_pledge_overlay.close_overlay()
        self.refresh()

    def _on_create_pledge_overlay_closed(self) -> None:
        self._pending_pledge_request = None
        self._pledge_overlay_context = None

    def _set_active_nav(self, active_name: str) -> None:
        self.sidebar.set_active_by_name(active_name)

    def _show_issues_page(self) -> None:
        self._set_active_nav("issues")
        self.content_stack.setCurrentWidget(self.issues_page)

    def _show_issue_detail_page(self, issue_id: UUID) -> None:
        issue = self.democracy_service.get_issue_with_votes(issue_id)
        if not issue:
            return

        solutions = self.democracy_service.get_solutions_for_issue_with_votes(issue_id)

        self.issue_detail_page.show_issue(
            issue,
            solutions,
        )
        self._set_active_nav("issues")
        self.content_stack.setCurrentWidget(self.issue_detail_page)

    def _open_create_solution_overlay(self, issue_id: UUID) -> None:
        self._solution_target_issue_id = issue_id
        self.create_solution_overlay.open_overlay()

    def _on_create_solution(self, draft: SolutionDraft) -> None:
        if self._solution_target_issue_id is None:
            return

        errors = draft.validate()
        if errors:
            return

        has_explicit_inactive_campaign = (
            draft.asking_price_satoshis == "0"
            and not draft.bitcoin_payout_address
            and not draft.deadline_height_offset
        )
        if (
            not has_explicit_inactive_campaign
            and any(
                (
                    draft.bitcoin_payout_address,
                    draft.asking_price_satoshis,
                    draft.deadline_height_offset,
                )
            )
        ):
            try:
                self.funding_service.bitcoin_rpc.get_block_count()
            except BitcoinRpcError:
                logger.exception(
                    "Failed to preflight funding campaign creation for issue %s.",
                    self._solution_target_issue_id,
                )
                return

        solution = self.democracy_service.create_solution(
            title=draft.title,
            description=draft.description,
            creator_id=self.user.id,
            issue_id=self._solution_target_issue_id,
        )
        self._create_campaign_for_solution(solution, draft)
        self.refresh()

    def _create_campaign_for_solution(
        self,
        solution: Solution,
        draft: SolutionDraft,
    ) -> None:
        asking_price_sats = 0
        deadline_height_offset: int | None = None
        developer_payout_address: str | None = None
        has_explicit_inactive_campaign = (
            draft.asking_price_satoshis == "0"
            and not draft.bitcoin_payout_address
            and not draft.deadline_height_offset
        )

        if (
            not has_explicit_inactive_campaign
            and any(
                (
                    draft.bitcoin_payout_address,
                    draft.asking_price_satoshis,
                    draft.deadline_height_offset,
                )
            )
        ):
            try:
                asking_price_sats = int(draft.asking_price_satoshis)
                deadline_height_offset = int(draft.deadline_height_offset)
            except ValueError:
                logger.warning(
                    "Failed to parse funding campaign fields for solution %s.",
                    solution.id,
                )
                return

            developer_payout_address = draft.bitcoin_payout_address

        try:
            self.funding_service.create_campaign(
                solution=solution,
                developer_payout_address=developer_payout_address,
                asking_price_sats=asking_price_sats,
                deadline_height_offset=deadline_height_offset,
            )
        except (BitcoinRpcError, ValueError):
            logger.exception(
                "Failed to create funding campaign for solution %s.",
                solution.id,
            )

    def _show_issue_detail_page_for_current_issue(self) -> None:
        current_id = self.issue_detail_page.current_issue_id
        if current_id is not None:
            self._show_issue_detail_page(current_id)

    def _on_vote_solution_directly(self, solution_id: UUID) -> None:
        current_issue_id = self.issue_detail_page.current_issue_id
        if current_issue_id is not None:
            self._on_solution_vote(current_issue_id, solution_id)

    def _on_code_verification_clicked(self, solution_id: UUID) -> None:
        logger.info(f"Open code verification for solution {solution_id}")

    def _show_torrents_page(self) -> None:
        self._set_active_nav("torrents")
        self.content_stack.setCurrentWidget(self.torrents_page)

    def _show_fleet_page(self) -> None:
        self._set_active_nav("fleet")
        self.content_stack.setCurrentWidget(self.fleet_page)

    def _show_experiment_page(self) -> None:
        self._set_active_nav("experiment")
        self.content_stack.setCurrentWidget(self.experiment_page)

    def _on_experiment_run_requested(
        self,
        dataset: str,
        algorithm: str,
        metric: str,
        queries: int,
        gossip: bool,
        hotswap_tick: int,
        hotswap_model: str,
    ) -> None:
        """Spawn a new LTRCommunityThread for this peer's distributed experiment."""
        if self._ltr_thread is not None:
            self._ltr_thread.stop()
            self._ltr_thread.wait(3000)
            self._ltr_thread = None

        thread = LTRCommunityThread(
            dataset_id=dataset,
            algorithm=algorithm,
            metric=metric,
            queries_per_round=queries,
            gossip_enabled=gossip,
            hotswap_round=hotswap_tick,
            hotswap_model=hotswap_model,
        )
        thread.started_ok.connect(
            self.experiment_page.on_started, type=Qt.ConnectionType.QueuedConnection
        )
        thread.snapshot.connect(
            self.experiment_page.on_snapshot, type=Qt.ConnectionType.QueuedConnection
        )
        thread.log_event.connect(
            self.experiment_page.on_log_event, type=Qt.ConnectionType.QueuedConnection
        )
        thread.finished_ok.connect(
            self.experiment_page.on_finished, type=Qt.ConnectionType.QueuedConnection
        )
        thread.error.connect(
            self.experiment_page.on_error, type=Qt.ConnectionType.QueuedConnection
        )
        thread.finished.connect(self._on_ltr_thread_finished)

        self._ltr_thread = thread
        thread.start()

    def _on_experiment_stop_requested(self) -> None:
        if self._ltr_thread is not None:
            self._ltr_thread.stop()

    def _on_ltr_thread_finished(self) -> None:
        # Allow the next RUN click to spawn a fresh thread
        self._ltr_thread = None

    def stop_ltr_thread(self) -> None:
        """Called from main on shutdown to stop any running experiment cleanly."""
        if self._ltr_thread is not None:
            self._ltr_thread.stop()
            self._ltr_thread.wait(2000)
            self._ltr_thread = None

    def _on_health_data_changed(self) -> None:
        self.torrents_page.load(self._health_thread.get_torrent_data())
        self.fleet_page.load(self._health_thread.get_fleet_data())
