import { Link } from "react-router-dom";
import "./legal.css";

export function PrivacyPolicyPage() {
    return (
        <div className="legal-page">
            <header className="legal-header">
                <Link to="/" className="legal-nav-back">
                    ← 서비스로 돌아가기
                </Link>
                <h1 className="legal-title">개인정보 처리방침</h1>
                <p className="legal-meta">시행일자: 2026년 8월 22일</p>
            </header>

            <main className="legal-content">
                <section className="legal-section">
                    <p>
                        <strong>MDLogger</strong>(이하 &quot;서비스&quot;)는 정보주체의 자유와 권리 보호를 위해 「개인정보 보호법」 및 관계 법령이 정한 바를 준수하여, 적법하게 개인정보를 처리하고 안전하게 관리하고 있습니다. 이에 「개인정보 보호법」 제30조에 따라 정보주체에게 개인정보 처리에 관한 절차 및 기준을 안내하고, 이와 관련한 고충을 신속하고 원활하게 처리할 수 있도록 하기 위하여 다음과 같이 개인정보 처리방침을 수립·공개합니다.
                    </p>
                    <p>
                        본 개인정보 처리방침은 MDLogger의 웹사이트, Windows 및 Linux 데스크톱 애플리케이션, 설치형 웹 애플리케이션(PWA)에 공통으로 적용됩니다.
                    </p>
                </section>

                <section className="legal-section">
                    <h2>제1조 (개인정보의 처리 목적)</h2>
                    <p>서비스는 다음의 목적을 위하여 개인정보를 처리합니다. 처리하고 있는 개인정보는 다음의 목적 이외의 용도로는 이용되지 않으며, 이용 목적이 변경되는 경우에는 「개인정보 보호법」 제18조에 따라 별도의 동의를 받는 등 필요한 조치를 이행할 예정입니다.</p>
                    <ol>
                        <li>
                            <strong>회원 가입 및 계정 관리</strong>
                            <br />
                            회원 가입 의사 확인, 회원제 서비스 제공에 따른 본인 식별·인증, 회원자격 유지·관리, 서비스 부정 이용 방지, 각종 고지·통지, 비밀번호 재설정, 계정 탈퇴 처리 등을 목적으로 개인정보를 처리합니다.
                        </li>
                        <li>
                            <strong>서비스 제공 및 데이터 동기화</strong>
                            <br />
                            게임 경기 기록의 저장 및 다중 기기간 동기화, 사용자 취향 설정(테마, UI 설정 등) 동기화, 기기별 동기화 상태 관리 등 서비스 제공 계약의 이행을 목적으로 개인정보를 처리합니다.
                        </li>
                        <li>
                            <strong>듀얼 메타 및 환경 통계 분석</strong>
                            <br />
                            사용자 게임 경기 통계의 분석, 듀얼 환경 통계 정보 생성 및 서비스 품질 향상을 목적으로 개인정보(가명 또는 개인을 식별할 수 없는 게임 관찰 데이터)를 처리합니다.
                        </li>
                        <li>
                            <strong>서비스 안정성 확보 및 보안</strong>
                            <br />
                            서비스 접속 안정성 유지, 악의적 트래픽 및 비정상 요청 방지, 시스템 오류 진단 및 보안 유지를 목적으로 최소한의 네트워크 로그를 처리합니다.
                        </li>
                    </ol>
                </section>

                <section className="legal-section">
                    <h2>제2조 (개인정보의 처리 및 보유 기간)</h2>
                    <p>① 서비스는 법령에 따른 개인정보 보유·이용 기간 또는 정보주체로부터 수집 시에 동의받거나 계약 체결 시 약정한 개인정보 보유·이용 기간 내에서 개인정보를 처리·보유합니다.</p>
                    <p>② 각각의 개인정보 처리 및 보유 기간은 다음과 같습니다.</p>
                    <ol>
                        <li>
                            <strong>회원 가입 및 계정 정보, 경기 동기화 기록: 회원 탈퇴 시까지</strong>
                            <ul>
                                <li>다만, 관계 법령 위반에 따른 수사·조사 등이 진행 중인 경우에는 해당 수사·조사 종료 시까지 보유합니다.</li>
                            </ul>
                        </li>
                        <li>
                            <strong>웹 접속 및 통신 로그: 수집 후 최대 30일 이내</strong>
                            <ul>
                                <li>Cloudflare 인프라 정책에 따라 보안 및 트래픽 분석 후 자동 파기됩니다.</li>
                            </ul>
                        </li>
                        <li>
                            <strong>게스트 듀얼 관찰 데이터: 통계 목적 달성 시까지</strong>
                            <ul>
                                <li>특정 개인을 식별할 수 없는 가명/익명 통계 데이터 형태로 관리됩니다.</li>
                            </ul>
                        </li>
                    </ol>
                </section>

                <section className="legal-section">
                    <h2>제3조 (처리하는 개인정보의 항목)</h2>
                    <p>서비스는 서비스 제공을 위해 필요한 최소한의 개인정보만을 처리하며, 이용 목적에 따라 처리하는 항목은 다음과 같습니다.</p>
                    
                    <h3>1. 회원 계정 이용 시 (공통)</h3>
                    <ul>
                        <li><strong>필수항목:</strong> 이메일 주소, 비밀번호(단방향 암호화 처리), 로그인 일시, 인증 토큰(Access/Refresh Token)</li>
                        <li><strong>수집 목적:</strong> 회원 식별, 로그인 인증, 보안 및 계정 관리</li>
                        <li><strong>법적 근거:</strong> 「개인정보 보호법」 제15조 제1항 제4호 (계약 체결 및 이행)</li>
                    </ul>

                    <h3>2. 경기 기록 동기화 이용 시 (공통)</h3>
                    <ul>
                        <li><strong>수집항목:</strong> 플레이 일시, 경기 결과(승/패), 선·후공, 사용 덱 및 상대 덱 분류, 진행 턴 수, 경기 종료 사유, 플레이 모드/문맥 ID, 랭크/레이팅/이벤트 점수 변동 기록, 개인 입력 메모, 장치 식별자(installation_id), 장치 표시 이름, 클라이언트 버전</li>
                        <li><strong>수집 목적:</strong> 기기간 경기 기록 동기화 및 전적 통계 제공</li>
                        <li><strong>법적 근거:</strong> 「개인정보 보호법」 제15조 제1항 제4호 (계약 체결 및 이행)</li>
                    </ul>

                    <h3>3. 클라이언트별 자동 생성·수집 정보</h3>
                    <ul>
                        <li><strong>웹/PWA 이용 시:</strong> 접속 IP 주소, User-Agent, 브라우저 정보, 세션 스토리지 정보 (Cloudflare 인프라 및 브라우저 런타임)</li>
                        <li><strong>Windows/Linux 데스크톱 앱 이용 시:</strong> 장치 고유 가명 식별자(installation_id, UUID), 앱 버전, 플랫폼 종류(Windows/Linux)</li>
                        <li><strong>덱 카탈로그 동기화 시 (데스크톱 앱):</strong> 최신 덱 목록 기준정보 조회를 위한 GitHub Gist 요청 시 전송되는 네트워크 정보(IP 주소, User-Agent: mdlogger-decks-sync)</li>
                    </ul>

                    <h3>4. 로컬 전용 처리 데이터 (서버 미전송)</h3>
                    <p>다음 정보는 사용자 기기 내부(로컬)에서만 저장 및 처리되며 운영자 서버로 전송되지 않습니다.</p>
                    <ul>
                        <li><strong>게스트 모드 개인 메모:</strong> 게스트 모드에서 작성된 메모(note)는 로컬 데이터베이스에만 저장되며 외부 분석 서버로 전송되지 않습니다.</li>
                        <li><strong>기기 전용 환경설정:</strong> UI 배율(ui_scale), 저사양 모드(low_spec_mode), 애니메이션 감소(reduce_motion), 글자 크기(font_scale)는 로컬 기기 맞춤 설정으로 서버에 동기화되지 않습니다.</li>
                        <li><strong>로컬 파일 경로 및 OS 사용자명:</strong> 오류 보고 SDK나 텔레메트리가 탑재되어 있지 않으며, 기기 내 파일 경로나 OS 사용자명은 외부로 일체 전송되지 않습니다.</li>
                    </ul>
                </section>

                <section className="legal-section">
                    <h2>제4조 (개인정보의 제3자 제공)</h2>
                    <p>서비스는 정보주체의 개인정보를 제1조(개인정보의 처리 목적)에서 명시한 범위 내에서만 처리하며, 정보주체의 동의, 법률의 특별한 규정 등 「개인정보 보호법」 제17조 및 제18조에 해당하는 경우에만 개인정보를 제3자에게 제공합니다.</p>
                    <p><strong>현재 서비스는 이용자의 개인정보를 제3자에게 제공하지 않습니다.</strong></p>
                </section>

                <section className="legal-section">
                    <h2>제5조 (개인정보 처리의 위탁)</h2>
                    <p>① 서비스는 원활한 개인정보 업무처리를 위하여 다음과 같이 개인정보 처리업무를 위탁하고 있습니다.</p>
                    <div className="legal-table-wrapper">
                        <table className="legal-table">
                            <thead>
                                <tr>
                                    <th>수탁자 (위탁받는 자)</th>
                                    <th>위탁하는 업무의 내용</th>
                                    <th>위탁 기간</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><strong>Supabase, Inc.</strong></td>
                                    <td>데이터베이스 호스팅, 사용자 인증(Auth) 관리, 서버리스 함수(Edge Functions) 실행, 백엔드 인프라 유지관리</td>
                                    <td>회원 탈퇴 시 또는 위탁계약 종료 시까지</td>
                                </tr>
                                <tr>
                                    <td><strong>Cloudflare, Inc.</strong></td>
                                    <td>웹 애플리케이션 호스팅(Workers Assets), 글로벌 CDN 에셋 서빙, 웹 보안(WAF 및 디도스 방어)</td>
                                    <td>서비스 이용 종료 시 또는 위탁계약 종료 시까지</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <p>② 서비스는 위탁계약 체결 시 「개인정보 보호법」 제26조에 따라 위탁업무 수행목적 외 개인정보 처리금지, 기술적·관리적 보호조치, 재위탁 제한, 수탁자에 대한 관리·감독, 손해배상 등 책임에 관한 사항을 명확히 규정하고, 수탁자가 개인정보를 안전하게 처리하는지를 감독하고 있습니다.</p>
                    <p>③ 위탁업무의 내용이나 수탁자가 변경될 경우에는 지체 없이 본 개인정보 처리방침을 통하여 공개하도록 하겠습니다.</p>
                </section>

                <section className="legal-section">
                    <h2>제6조 (개인정보의 국외 이전)</h2>
                    <p>서비스는 클라우드 인프라 및 서비스 제공을 위해 다음과 같이 개인정보를 국외로 처리위탁 및 보관하고 있습니다. 본 국외 이전은 서비스 제공 및 계약 이행을 위해 필수적인 항목입니다(「개인정보 보호법」 제28조의8 제1항 제3호).</p>
                    
                    <h3>1. Supabase, Inc.</h3>
                    <ul>
                        <li><strong>이전되는 개인정보 항목:</strong> 계정 이메일, 암호화된 비밀번호, 인증 토큰, 경기 기록 데이터, 장치 식별 정보, 취향 설정</li>
                        <li><strong>이전 국가:</strong> 대한민국 (서울 리전 Primary DB) 및 미국 등 Supabase 글로벌 인프라 소재국</li>
                        <li><strong>이전 시기 및 방법:</strong> 회원가입, 로그인, 경기 동기화 시 인터넷망을 통한 암호화(HTTPS/TLS) 전송</li>
                        <li><strong>이전받는 자:</strong> Supabase, Inc. (privacy@supabase.com)</li>
                        <li><strong>이전받는 자의 이용목적:</strong> 클라우드 데이터베이스 운영, 사용자 인증 및 세션 관리, Edge Functions 처리</li>
                        <li><strong>보유 및 이용기간:</strong> 회원 탈퇴 시 또는 서비스 종료 시까지</li>
                        <li><strong>이전 거부 방법 및 효과:</strong> 정보주체는 서비스 회원가입을 진행하지 않거나 회원 탈퇴를 요청함으로써 국외 이전을 거부할 수 있습니다. 단, 거부 시 온라인 계정 생성 및 기기간 동기화 서비스 이용이 제한됩니다.</li>
                    </ul>

                    <h3>2. Cloudflare, Inc.</h3>
                    <ul>
                        <li><strong>이전되는 개인정보 항목:</strong> 웹사이트 접속 시의 네트워크 정보 (IP 주소, User-Agent, 접속 일시)</li>
                        <li><strong>이전 국가:</strong> 미국 및 Cloudflare 글로벌 네트워크 거점국</li>
                        <li><strong>이전 시기 및 방법:</strong> 웹사이트 접속 및 API 호출 시 네트워크 라우팅을 통한 전송</li>
                        <li><strong>이전받는 자:</strong> Cloudflare, Inc. (privacyquestions@cloudflare.com)</li>
                        <li><strong>이전받는 자의 이용목적:</strong> 웹 정적 에셋 호스팅, 트래픽 분산 및 네트워크 보안</li>
                        <li><strong>보유 및 이용기간:</strong> 보안 로그 정책에 따라 최대 30일 이내 자동 파기</li>
                        <li><strong>이전 거부 방법 및 효과:</strong> 웹사이트 이용을 중단함으로써 거부할 수 있으며, 거부 시 웹 클라이언트 이용이 불가능합니다.</li>
                    </ul>

                    <h3>3. GitHub, Inc. (Microsoft Corporation)</h3>
                    <ul>
                        <li><strong>이전되는 개인정보 항목:</strong> 데스크톱 앱의 최신 덱 카탈로그 조회 시 요청 네트워크 정보 (IP 주소, User-Agent)</li>
                        <li><strong>이전 국가:</strong> 미국</li>
                        <li><strong>이전 시기 및 방법:</strong> 데스크톱 앱 실행 시 최신 덱 목록(GitHub Gist) 동기화 요청</li>
                        <li><strong>이전받는 자:</strong> GitHub, Inc. (privacy@github.com)</li>
                        <li><strong>이전받는 자의 이용목적:</strong> 최신 덱 카탈로그 기준정보 제공</li>
                        <li><strong>보유 및 이용기간:</strong> GitHub 로깅 정책에 따름</li>
                        <li><strong>이전 거부 방법 및 효과:</strong> 네트워크 연결 없이 오프라인 모드로 앱을 사용하거나 환경변수(<code>MDLOGGER_DECKS_URL</code>)를 빈 값으로 설정(<code>MDLOGGER_DECKS_URL=</code>)하여 동기화를 비활성화할 수 있습니다.</li>
                    </ul>
                </section>

                <section className="legal-section">
                    <h2>제7조 (개인정보의 파기 절차 및 방법)</h2>
                    <p>① 서비스는 개인정보 보유기간의 경과, 처리목적 달성 등 개인정보가 불필요하게 되었을 때에는 지체 없이 해당 개인정보를 파기합니다.</p>
                    <p>② 정보주체가 회원 탈퇴를 요청하는 경우, 서비스는 다음의 절차에 따라 개인정보를 즉시 파기합니다.</p>
                    <ul>
                        <li><strong>계정 삭제 시:</strong> Supabase Auth 사용자가 영구 삭제되며, 연계된 개인 경기 기록(<code>games</code>), 프로필(<code>profiles</code>), 등록 장치(<code>devices</code>), 동기화 커서(<code>game_change_cursors</code>), 설정(<code>user_settings</code>)이 외래키 연쇄 삭제(FK Cascade)를 통해 데이터베이스에서 완전히 즉시 파기됩니다.</li>
                        <li><strong>로컬 데이터 삭제 시:</strong> 데스크톱 앱의 &apos;앱 초기화&apos; 기능을 통해 기기 내 저장된 로컬 SQLite 데이터베이스, 설정 파일, 캐시 및 저장된 인증 토큰을 모두 영구 삭제할 수 있습니다.</li>
                    </ul>
                    <p>③ 전자적 파일 형태의 정보는 기록을 재생할 수 없는 기술적 방법을 사용하여 영구 삭제합니다.</p>
                </section>

                <section className="legal-section">
                    <h2>제8조 (정보주체와 법정대리인의 권리·의무 및 행사방법)</h2>
                    <p>① 정보주체는 서비스에 대해 언제든지 다음 각 호의 개인정보 보호 관련 권리를 행사할 수 있습니다.</p>
                    <ol>
                        <li>개인정보 열람 요구</li>
                        <li>오류 등이 있을 경우 정정 요구</li>
                        <li>삭제 요구 (회원 탈퇴)</li>
                        <li>처리정지 요구</li>
                        <li>개인정보 전송 요구 (데이터 내보내기)</li>
                    </ol>
                    <p>② 정보주체는 서비스 내 [설정] → [계정 및 데이터] 메뉴를 통해 자신의 개인정보를 직접 열람, 수정, 내보내기(JSON 다운로드), 삭제(회원 탈퇴)할 수 있습니다.</p>
                    <p>③ 또한 제11조에 기재된 개인정보 보호책임자 또는 문의처로 전자우편(이메일)을 통해 권리 행사를 요청하실 수 있으며, 서비스는 이에 대해 지체 없이 조치하겠습니다.</p>
                    <p>④ 정보주체가 개인정보의 오류 등에 대한 정정 또는 삭제를 요구한 경우에는 정정 또는 삭제를 완료할 때까지 당해 개인정보를 이용하거나 제공하지 않습니다.</p>
                    <p>⑤ 서비스는 만 14세 미만 아동의 개인정보를 수집하지 않으며, 만 14세 미만 아동의 회원 가입 사실이 확인될 경우 지체 없이 해당 개인정보 및 계정을 영구 파기합니다.</p>
                </section>

                <section className="legal-section">
                    <h2>제9조 (개인정보의 안전성 확보 조치)</h2>
                    <p>서비스는 「개인정보 보호법」 제29조에 따라 다음과 같이 안전성 확보에 필요한 기술적·관리적 및 물리적 조치를 하고 있습니다.</p>
                    <ol>
                        <li>
                            <strong>인증 자격증명의 안전한 암호화 및 보관</strong>
                            <ul>
                                <li>비밀번호는 복호화가 불가능한 일방향 암호화 해시 알고리즘으로 처리되어 저장되며 운영자도 이를 알 수 없습니다.</li>
                                <li>데스크톱 앱의 장기 인증 토큰(Refresh Token)은 운영체제(OS) 표준 보안 저장소(Windows Credential Manager, Linux Secret Service)에 안전하게 암호화 보관됩니다.</li>
                            </ul>
                        </li>
                        <li>
                            <strong>네트워크 전송 암호화</strong>
                            <ul>
                                <li>클라이언트와 서버 간의 모든 데이터 전송은 최신 표준 전송 계층 보안(HTTPS / TLS)을 통해 암호화되어 보호됩니다.</li>
                            </ul>
                        </li>
                        <li>
                            <strong>데이터베이스 접근 제어 및 행 단위 보안(RLS)</strong>
                            <ul>
                                <li>데이터베이스 수준에서 Row Level Security(RLS)를 적용하여, 인증된 사용자 본인의 경기 데이터에만 접근할 수 있도록 격리하고 있습니다.</li>
                                <li>클라이언트에는 관리자 권한 키(Service Role Key)가 전혀 포함되지 않으며 최소 권한의 공개 키(Anon Key)만을 사용합니다.</li>
                            </ul>
                        </li>
                        <li>
                            <strong>로컬 데이터 접근 권한 제한</strong>
                            <ul>
                                <li>데스크톱 애플리케이션의 로컬 데이터 파일 및 디렉터리는 POSIX 환경에서 현재 사용자만 읽고 쓸 수 있는 전용 권한(0700/0600)을 적용하여 다른 로컬 사용자의 무단 접근을 방지합니다.</li>
                            </ul>
                        </li>
                    </ol>
                </section>

                <section className="legal-section">
                    <h2>제10조 (개인정보 자동 수집 장치의 설치·운영 및 거부에 관한 사항)</h2>
                    <p>① 서비스는 이용자에게 개별적인 맞춤서비스를 제공하기 위해 이용정보를 저장하고 수시로 불러오는 &apos;쿠키(cookie)&apos; 및 로컬 스토리지(LocalStorage/IndexedDB)를 사용할 수 있습니다.</p>
                    <p>② 쿠키 및 스토리지는 이용자의 로그인 세션 유지, 테마 및 입력 방식 등 사용자 취향 설정 기억을 위한 필수적인 기능에만 사용됩니다.</p>
                    <p>③ 서비스는 광고성 트래커, 제3자 마케팅 분석 도구를 사용하지 않습니다.</p>
                    <p>④ 이용자는 웹 브라우저의 옵션 설정을 통해 쿠키 저장을 거부하거나 삭제할 수 있습니다. 단, 쿠키 저장을 거부할 경우 웹 버전의 자동 로그인 등 일부 기능 이용에 어려움이 있을 수 있습니다.</p>
                </section>

                <section className="legal-section">
                    <h2>제11조 (개인정보 보호책임자 및 고충처리 연락처)</h2>
                    <p>서비스는 개인정보 처리에 관한 업무를 총괄해서 책임지고, 개인정보 처리와 관련한 정보주체의 불만처리 및 피해구제 등을 위하여 아래와 같이 개인정보 보호책임자를 지정하고 있습니다.</p>
                    <ul>
                        <li><strong>개인정보 보호책임자 / 담당 부서</strong>
                            <ul>
                                <li>운영 주체: 노연우</li>
                                <li>문의처: ahsjdkfl1177@gmail.com</li>
                                <li>연락처: 서비스 내 문의 채널 또는 이메일</li>
                            </ul>
                        </li>
                    </ul>
                    <p>정보주체는 서비스의 서비스를 이용하시면서 발생한 모든 개인정보 보호 관련 문의, 불만처리, 피해구제 등에 관한 사항을 개인정보 보호책임자 및 담당부서로 문의하실 수 있습니다. 서비스는 정보주체의 문의에 대해 지체 없이 답변 및 처리해드릴 것입니다.</p>
                </section>

                <section className="legal-section">
                    <h2>제12조 (개인정보 처리방침의 변경)</h2>
                    <p>① 이 개인정보 처리방침은 <strong>2026년 8월 22일</strong>부터 적용됩니다.</p>
                    <p>② 이전의 개인정보 처리방침 이력은 버전 관리 시스템 및 서비스 공지를 통해 언제든지 열람할 수 있도록 제공됩니다.</p>
                </section>

                <footer className="legal-footer-links">
                    <Link to="/terms">서비스 이용약관 보기</Link>
                    <Link to="/">홈으로</Link>
                </footer>
            </main>
        </div>
    );
}
