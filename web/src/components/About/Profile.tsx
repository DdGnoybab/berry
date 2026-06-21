import { profile } from '../../data/profile'

export function Profile() {
  return (
    <section className="about-profile">
      <header className="about-profile__head">
        <h1 className="about-profile__brand">{profile.brand}</h1>
        <div className="about-profile__rule" aria-hidden="true" />
      </header>

      <p className="about-profile__tagline">{profile.tagline}</p>

      <div className="about-profile__bio">
        {profile.bio.map((para, i) => (
          <p key={i}>{para}</p>
        ))}
      </div>

      {profile.now.length > 0 && (
        <div className="about-profile__block">
          <h2 className="about-profile__block-title">「 在做的事 」</h2>
          <ul className="about-profile__now">
            {profile.now.map((item, i) => (
              <li key={i}>
                <span className="about-profile__now-marker" aria-hidden="true">
                  ▸
                </span>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {profile.skills.length > 0 && (
        <div className="about-profile__block">
          <h2 className="about-profile__block-title">「 技能栈 」</h2>
          <div className="about-profile__skills">
            {profile.skills.map((s) => (
              <span key={s} className="about-tag">
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {profile.links.length > 0 && (
        <div className="about-profile__block">
          <h2 className="about-profile__block-title">「 联系方式 」</h2>
          <div className="about-profile__links">
            {profile.links.map((l) => (
              <a
                key={l.label}
                href={l.href}
                className="about-link"
                target={l.href.startsWith('http') ? '_blank' : undefined}
                rel={l.href.startsWith('http') ? 'noopener noreferrer' : undefined}
              >
                {l.label}
              </a>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
