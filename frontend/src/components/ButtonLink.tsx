import type { LinkProps } from 'react-router-dom'
import { Link } from 'react-router-dom'

export function ButtonLink(props: LinkProps & { variant?: 'primary' | 'default'; size?: 'sm' | 'md' }) {
  const { className, variant = 'default', size = 'md', ...rest } = props
  const cls = `btnLink ${size === 'sm' ? 'btnSm' : ''} ${variant === 'primary' ? 'btnPrimary' : ''} ${
    className || ''
  }`.trim()
  return <Link {...rest} className={cls} />
}


