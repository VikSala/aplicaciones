/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class AmazonDashboard extends Component {
    static template = "AmazonDashboard";

    setup() {
        this.orm = useService('orm');
        this.actionService = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            accounts: [],
            selectedAccountId: "all",
            files: [],
            filteredFiles: [],
            searchQuery: "",
            filterType: "ALL FILES",
            loading: true,
            error: null,
            previewFile: null,
            viewMode: "grid",
            sortField: null,
            sortAsc: true,
            // Pagination
            page: 1,
            hasNextPage: false,
        });

        // tokenHistory[0] = null (page 1 needs no token)
        // tokenHistory[1] = tokens for page 2, etc.
        this.tokenHistory = [null];

        onWillStart(async () => {
            await this.loadAccounts();
            await this.fetchPage();
        });
    }

    async loadAccounts() {
        const accounts = await this.orm.call('amazon.dashboard', 'get_s3_accounts', [[]]);
        this.state.accounts = accounts;
        this.state.selectedAccountId = "all";
    }

    async fetchPage() {
        this.state.loading = true;
        this.state.error = null;
        try {
            if (this.state.accounts.length === 0) {
                this.state.error = "No S3 accounts configured. Please add an account from the S3 Accounts menu.";
                this.state.loading = false;
                return;
            }
            const accountId = this.state.selectedAccountId;
            const pageIndex = this.state.page - 1;
            const pageTokens = this.tokenHistory[pageIndex] || null;

            const result = await this.orm.call(
                'amazon.dashboard', 'amazon_view_files',
                [[]], {account_id: accountId, page_tokens: pageTokens}
            );
            if (!result) {
                this.state.error = "Please configure your Amazon S3 accounts in the S3 Accounts menu.";
                this.notification.add("Please set up an S3 Account", { type: "warning" });
            } else if (result.error) {
                this.state.error = "Failed to load files: " + result.error;
                this.notification.add("Failed to load files: " + result.error, { type: "warning" });
            } else {
                this.state.files = result.files;
                this.state.hasNextPage = result.has_next;
                // Store tokens for the next page
                if (result.has_next && result.next_tokens) {
                    this.tokenHistory[this.state.page] = result.next_tokens;
                }
                this.applyFilters();
            }
        } catch (e) {
            this.state.error = "An unexpected error occurred.";
        }
        this.state.loading = false;
    }

    _resetPagination() {
        this.state.page = 1;
        this.state.hasNextPage = false;
        this.tokenHistory = [null];
    }

    async onAccountChange(ev) {
        const val = ev.target.value;
        this.state.selectedAccountId = val === "all" ? "all" : parseInt(val);
        this.state.previewFile = null;
        this._resetPagination();
        await this.fetchPage();
    }

    async nextPage() {
        if (!this.state.hasNextPage) return;
        this.state.page += 1;
        this.state.previewFile = null;
        await this.fetchPage();
    }

    async prevPage() {
        if (this.state.page <= 1) return;
        this.state.page -= 1;
        this.state.previewFile = null;
        await this.fetchPage();
    }

    applyFilters() {
        let files = [...this.state.files];
        if (this.state.searchQuery) {
            const q = this.state.searchQuery.toLowerCase();
            files = files.filter(f => f.name.toLowerCase().includes(q));
        }
        if (this.state.filterType !== "ALL FILES") {
            files = files.filter(f => {
                const ext = f.extension;
                switch (this.state.filterType) {
                    case "pdf": return ext === "pdf";
                    case "image": return ["jpeg", "jpg", "png", "gif", "bmp", "webp", "svg"].includes(ext);
                    case "zip": return ext === "zip";
                    case "txt": return ["txt", "docx"].includes(ext);
                    case "xlsx": return ext === "xlsx";
                    default: return true;
                }
            });
        }
        if (this.state.sortField) {
            const field = this.state.sortField;
            const asc = this.state.sortAsc;
            files.sort((a, b) => {
                const va = (a[field] || "").toString().toLowerCase();
                const vb = (b[field] || "").toString().toLowerCase();
                const cmp = va.localeCompare(vb, undefined, { numeric: true });
                return asc ? cmp : -cmp;
            });
        }
        this.state.filteredFiles = files;
    }

    onSearchInput(ev) {
        this.state.searchQuery = ev.target.value;
        this.applyFilters();
    }

    onFilterChange(ev) {
        this.state.filterType = ev.target.value;
        this.applyFilters();
    }

    sortBy(field) {
        if (this.state.sortField === field) {
            this.state.sortAsc = !this.state.sortAsc;
        } else {
            this.state.sortField = field;
            this.state.sortAsc = true;
        }
        this.applyFilters();
    }

    toggleView(mode) {
        this.state.viewMode = mode;
    }

    selectFile(file) {
        this.state.previewFile = file;
    }

    closePreview() {
        this.state.previewFile = null;
    }

    upload() {
        this.actionService.doAction({
            name: "Upload File",
            type: 'ir.actions.act_window',
            res_model: 'amazon.upload.file',
            view_mode: 'form',
            view_type: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: {
                default_account_id: this.state.selectedAccountId !== "all"
                    ? this.state.selectedAccountId : undefined,
            },
        });
    }

    async refresh() {
        this.state.previewFile = null;
        this._resetPagination();
        await this.fetchPage();
    }

    getFileIcon(file) {
        const ext = file.extension;
        if (file.is_image) return "fa-file-image-o";
        if (file.is_pdf) return "fa-file-pdf-o";
        if (["zip", "rar", "7z", "tar", "gz"].includes(ext)) return "fa-file-archive-o";
        if (["doc", "docx", "txt", "rtf"].includes(ext)) return "fa-file-text-o";
        if (["xls", "xlsx", "csv"].includes(ext)) return "fa-file-excel-o";
        if (["ppt", "pptx"].includes(ext)) return "fa-file-powerpoint-o";
        if (["mp4", "avi", "mov", "mkv"].includes(ext)) return "fa-file-video-o";
        if (["mp3", "wav", "flac"].includes(ext)) return "fa-file-audio-o";
        return "fa-file-o";
    }

    getIconColor(file) {
        const ext = file.extension;
        if (file.is_image) return "#4CAF50";
        if (file.is_pdf) return "#F44336";
        if (["zip", "rar", "7z", "tar", "gz"].includes(ext)) return "#FF9800";
        if (["doc", "docx", "txt", "rtf"].includes(ext)) return "#2196F3";
        if (["xls", "xlsx", "csv"].includes(ext)) return "#4CAF50";
        return "#9E9E9E";
    }

    getSortIcon(field) {
        if (this.state.sortField !== field) return "fa-sort";
        return this.state.sortAsc ? "fa-sort-asc" : "fa-sort-desc";
    }
}

registry.category("actions").add("amazon_dashboard", AmazonDashboard);
