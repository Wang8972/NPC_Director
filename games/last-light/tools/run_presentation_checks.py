"""Compile and run the real C# presentation clock/timeline without Unity or models."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,tempfile
from xml.sax.saxutils import escape
ROOT=Path(__file__).resolve().parents[1]
SOURCES=['Assets/LastLight/Scripts/Net/GameDtos.cs','Assets/LastLight/Scripts/World/PresentationClock.cs',
         'Assets/LastLight/Scripts/World/PerformanceTimeline.cs','Assets/LastLight/Scripts/QA/PresentationContractChecks.cs']

def main():
    bundled=ROOT/'tools/.dotnet/dotnet'
    dotnet=str(bundled) if bundled.exists() else shutil.which('dotnet')
    if not dotnet:raise RuntimeError('Install .NET 8 SDK to run the C# presentation checks.')
    with tempfile.TemporaryDirectory(prefix='lastlight-presentation-') as folder:
        work=Path(folder)
        includes=''.join('<Compile Include="'+escape(str(ROOT/path),{'"':'&quot;'})+'" />' for path in SOURCES)
        (work/'Checks.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><EnableDefaultCompileItems>false</EnableDefaultCompileItems><Nullable>disable</Nullable><LangVersion>9</LangVersion></PropertyGroup><ItemGroup><Compile Include="Program.cs"/>'+includes+'</ItemGroup></Project>')
        (work/'Program.cs').write_text('using System; using System.Text.Json; using LastLight.QA; class Program { static int Main(){var failures=PresentationContractChecks.Run(); Console.WriteLine(JsonSerializer.Serialize(new {assertions=PresentationContractChecks.AssertionCount,failures}));return failures.Length==0?0:1;} }')
        env={**os.environ,'DOTNET_CLI_TELEMETRY_OPTOUT':'1'}
        subprocess.run([dotnet,'build',str(work/'Checks.csproj'),'--configfile',str(ROOT/'tools/MockRenderer/NuGet.Config'),'--nologo','-v','quiet'],check=True,env=env)
        result=subprocess.run([dotnet,str(work/'bin/Debug/net8.0/Checks.dll')],text=True,capture_output=True,env=env)
        data=json.loads(result.stdout.strip().splitlines()[-1]);data.update(suite='PresentationContractChecks',exit_code=result.returncode,runtime='dotnet / net8.0',unity_player_run=False,model_calls=0,
            sources=[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in SOURCES])
        destination=ROOT/'artifacts/presentation/csharp-timeline-tests.json';destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');print(json.dumps(data,ensure_ascii=False))
        if result.returncode:raise SystemExit(result.returncode)
if __name__=='__main__':main()
