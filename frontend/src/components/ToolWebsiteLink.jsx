import React from 'react'
import { safeWebsite } from '../toolEvidence'
import { FavouriteButton } from '../favourites/Favourites'

export default function ToolWebsiteLink({ toolId, name, url, summary, compare }) {
  const site = safeWebsite(url)
  return (
    <li className="tool-site">
      <div className="tool-site-text">
        <span className="tool-site-name">{name}</span>
        {summary && <span className="tool-site-summary">{summary}</span>}
      </div>
      <div className="tool-site-actions">
        {compare}
        {site && <a className="tool-site-link" href={site} target="_blank" rel="noopener noreferrer">Visit website<span className="sr-only"> for {name} (opens in a new tab)</span><span aria-hidden="true"> ↗</span></a>}
        {toolId && <FavouriteButton toolId={toolId} name={name} />}
      </div>
    </li>
  )
}
