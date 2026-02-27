/**
 * StatusBadge - A unified, standardized badge component for displaying statuses.
 * Matches the modern UI design system for the application.
 */
import { type ComponentChildren } from 'preact';
import {
    CheckCircle2,
    AlertTriangle,
    XCircle,
    Info,
    HelpCircle,
    type LucideIcon,
} from 'lucide-react';

export type StatusBadgeVariant =
    | 'success'
    | 'warning'
    | 'error'
    | 'danger'
    | 'info'
    | 'primary'
    | 'unknown'
    | 'inactive';

export interface StatusBadgeProps {
    variant?: StatusBadgeVariant;
    icon?: LucideIcon | null; // Pass `null` to explicitly remove the icon
    children?: ComponentChildren;
    class?: string;
}

const DEFAULT_ICONS: Record<StatusBadgeVariant, LucideIcon> = {
    success: CheckCircle2,
    warning: AlertTriangle,
    error: XCircle,
    danger: XCircle,
    info: Info,
    primary: CheckCircle2,
    unknown: HelpCircle,
    inactive: HelpCircle,
};

export function StatusBadge({
    variant = 'info',
    icon,
    children,
    class: customClass = '',
}: StatusBadgeProps) {
    // If `icon` is explicitly null, don't show an icon.
    // If `icon` is provided, use it. Otherwise, fallback to the default for this variant.
    const Icon = icon === null ? null : (icon || DEFAULT_ICONS[variant]);
    const badgeClass = `ics-status-badge-unified ics-status-badge-unified--${variant} ${customClass}`.trim();

    return (
        <span class={badgeClass}>
            {Icon && <Icon size={14} />}
            <span>{children}</span>
        </span>
    );
}
